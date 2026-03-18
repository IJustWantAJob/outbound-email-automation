"""Email queue management -- scheduling, spreading, and processing."""

from datetime import datetime, timedelta, timezone, time

import pytz

from database import db
from models import Campaign, Contact, Email, Reply


def generate_daily_queue(campaign_id):
    """Generate today's send queue for a campaign.

    Logic:
    1. Find emails that need sending today:
       a. Initial emails for contacts with status='pending' (in wave order)
       b. Follow-up 1 emails where initial was sent >= followup1_delay_days ago
          AND no reply
       c. Follow-up 2 emails where initial was sent >= followup2_delay_days ago
          AND no reply
    2. Limit to campaign.max_emails_per_day
    3. Spread emails across the send window at campaign.min_interval_minutes apart
    4. Set each email status to 'scheduled' with a scheduled_at timestamp

    Returns:
        Number of emails scheduled.
    """
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign or campaign.status != 'active':
        return 0

    tz = pytz.timezone(campaign.timezone)
    now = datetime.now(tz)
    today = now.date()

    # Collect emails to send
    to_send = []

    # 1. Due follow-ups (priority over new initials -- don't let follow-ups pile up)
    due_followups = find_due_followups(campaign_id, today, campaign)
    to_send.extend(due_followups)

    # 2. Pending initials (in wave order, then external_id order)
    if len(to_send) < campaign.max_emails_per_day:
        remaining_slots = campaign.max_emails_per_day - len(to_send)
        pending_initials = find_pending_initials(campaign_id, remaining_slots)
        to_send.extend(pending_initials)

    # 3. Limit to max per day
    to_send = to_send[: campaign.max_emails_per_day]

    if not to_send:
        return 0

    # 4. Spread across send window
    send_start = tz.localize(
        datetime.combine(today, time(campaign.send_start_hour, 0))
    )

    # If we're past the start time, start from now (rounded up to next interval)
    if now > send_start:
        minutes_since_start = (now - send_start).total_seconds() / 60
        next_slot = int(minutes_since_start / campaign.min_interval_minutes) + 1
        send_start = send_start + timedelta(
            minutes=next_slot * campaign.min_interval_minutes
        )

    count = 0
    for i, email in enumerate(to_send):
        send_time = send_start + timedelta(
            minutes=i * campaign.min_interval_minutes
        )

        # Don't schedule past end hour
        send_end = tz.localize(
            datetime.combine(today, time(campaign.send_end_hour, 0))
        )
        if send_time >= send_end:
            break

        email.status = 'scheduled'
        email.scheduled_at = send_time.astimezone(timezone.utc)  # Store as UTC
        count += 1

    db.session.commit()
    return count


def find_pending_initials(campaign_id, limit):
    """Find initial emails for contacts that haven't been emailed yet.

    Returns in wave order, then external_id order.
    """
    contacts = (
        Contact.query.filter_by(campaign_id=campaign_id, status='pending')
        .order_by(Contact.wave.asc(), Contact.external_id.asc())
        .limit(limit)
        .all()
    )

    emails = []
    for contact in contacts:
        initial = Email.query.filter_by(
            contact_id=contact.id, email_type='initial', status='draft'
        ).first()
        if initial:
            emails.append(initial)

    return emails


def find_due_followups(campaign_id, today, campaign):
    """Find follow-up emails that are due today.

    FU1: initial sent >= followup1_delay_days ago, contact status = initial_sent
    FU2: initial sent >= followup2_delay_days ago, contact status = followup1_sent
    Only if contact has NOT replied, bounced, or opted out.
    """
    due = []

    # Contacts eligible for follow-ups (not replied/bounced/opted_out)
    eligible_statuses = ['initial_sent', 'followup1_sent']
    contacts = Contact.query.filter(
        Contact.campaign_id == campaign_id,
        Contact.status.in_(eligible_statuses),
    ).all()

    for contact in contacts:
        # Double-check no reply exists
        has_reply = Reply.query.filter_by(contact_id=contact.id).first()
        if has_reply:
            continue

        initial = Email.query.filter_by(
            contact_id=contact.id, email_type='initial', status='sent'
        ).first()
        if not initial or not initial.sent_at:
            continue

        days_since = (today - initial.sent_at.date()).days

        # Check FU1
        if (
            contact.status == 'initial_sent'
            and days_since >= campaign.followup1_delay_days
        ):
            fu1 = Email.query.filter_by(
                contact_id=contact.id, email_type='followup1', status='draft'
            ).first()
            if fu1:
                due.append(fu1)

        # Check FU2
        elif (
            contact.status == 'followup1_sent'
            and days_since >= campaign.followup2_delay_days
        ):
            fu2 = Email.query.filter_by(
                contact_id=contact.id, email_type='followup2', status='draft'
            ).first()
            if fu2:
                due.append(fu2)

    return due


def process_queue():
    """Process the email queue -- send any emails whose scheduled_at is past."""
    now = datetime.now(timezone.utc)

    due_emails = (
        Email.query.filter(
            Email.status == 'scheduled', Email.scheduled_at <= now
        )
        .order_by(Email.scheduled_at.asc())
        .all()
    )

    results = []
    for email in due_emails:
        contact = email.contact

        # SAFETY: Re-check for replies before sending follow-ups
        if email.email_type in ('followup1', 'followup2'):
            has_reply = Reply.query.filter_by(contact_id=contact.id).first()
            if has_reply:
                email.status = 'cancelled'
                db.session.commit()
                results.append((email.id, 'cancelled_reply_detected'))
                continue

        try:
            from gmail.sender import send_email

            msg_id, thread_id = send_email(email)
            results.append((email.id, 'sent'))
        except Exception as e:
            results.append((email.id, f'failed: {e}'))

    return results


def generate_daily_queue_for_active_campaigns():
    """Generate daily queue for all active campaigns."""
    campaigns = Campaign.query.filter_by(status='active').all()
    total = 0
    for campaign in campaigns:
        total += generate_daily_queue(campaign.id)
    return total


def simulate_schedule(campaign_id, days=7):
    """Simulate the next N days of email sends for a campaign.

    This does NOT modify the database. It projects what generate_daily_queue
    would schedule each day based on current contact/email statuses.

    Returns a list of dicts, one per day:
        {
            'date': '2026-03-05',
            'day_label': 'Tomorrow',
            'emails': [
                {'contact_name': '...', 'company': '...', 'email_type': 'initial',
                 'subject': '...', 'wave': 1, 'email_confidence': 'HIGH',
                 'contact_email': '...'}
            ]
        }
    """
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return []

    tz = pytz.timezone(campaign.timezone)
    today = datetime.now(tz).date()
    max_per_day = campaign.max_emails_per_day

    # Build a snapshot of current state that we'll mutate in-memory
    contacts = Contact.query.filter_by(campaign_id=campaign_id).order_by(
        Contact.wave.asc(), Contact.external_id.asc()
    ).all()

    # Track simulated state per contact
    sim_state = {}
    for c in contacts:
        # Find what's already sent
        initial_sent_email = Email.query.filter_by(
            contact_id=c.id, email_type='initial', status='sent'
        ).first()

        sim_state[c.id] = {
            'contact': c,
            'status': c.status,
            'initial_sent_date': initial_sent_email.sent_at.date() if initial_sent_email and initial_sent_email.sent_at else None,
            'fu1_sent': c.status in ('followup1_sent', 'followup2_sent', 'completed'),
            'fu2_sent': c.status in ('followup2_sent', 'completed'),
            'has_reply': Reply.query.filter_by(contact_id=c.id).first() is not None,
            'has_initial_draft': Email.query.filter_by(
                contact_id=c.id, email_type='initial', status='draft'
            ).first() is not None,
            'has_fu1_draft': Email.query.filter_by(
                contact_id=c.id, email_type='followup1', status='draft'
            ).first() is not None,
            'has_fu2_draft': Email.query.filter_by(
                contact_id=c.id, email_type='followup2', status='draft'
            ).first() is not None,
        }

    schedule = []
    day_labels = ['Today', 'Tomorrow']

    for day_offset in range(days):
        sim_date = today + timedelta(days=day_offset)
        day_emails = []

        if day_offset < len(day_labels):
            label = day_labels[day_offset]
        else:
            label = sim_date.strftime('%A %b %d')

        # 1. Due follow-ups (priority)
        for cid, state in sim_state.items():
            if state['has_reply']:
                continue
            c = state['contact']

            if state['initial_sent_date'] and not state['fu1_sent'] and state['has_fu1_draft']:
                days_since = (sim_date - state['initial_sent_date']).days
                if days_since >= campaign.followup1_delay_days:
                    fu1_email = Email.query.filter_by(
                        contact_id=c.id, email_type='followup1'
                    ).first()
                    day_emails.append({
                        'contact_name': c.name,
                        'company': c.company,
                        'contact_email': c.email,
                        'email_type': 'followup1',
                        'subject': fu1_email.subject if fu1_email else '(follow-up 1)',
                        'wave': c.wave,
                        'email_confidence': c.email_confidence,
                    })
                    if len(day_emails) >= max_per_day:
                        break

            elif state['initial_sent_date'] and state['fu1_sent'] and not state['fu2_sent'] and state['has_fu2_draft']:
                days_since = (sim_date - state['initial_sent_date']).days
                if days_since >= campaign.followup2_delay_days:
                    fu2_email = Email.query.filter_by(
                        contact_id=c.id, email_type='followup2'
                    ).first()
                    day_emails.append({
                        'contact_name': c.name,
                        'company': c.company,
                        'contact_email': c.email,
                        'email_type': 'followup2',
                        'subject': fu2_email.subject if fu2_email else '(follow-up 2)',
                        'wave': c.wave,
                        'email_confidence': c.email_confidence,
                    })
                    if len(day_emails) >= max_per_day:
                        break

        # 2. Pending initials
        if len(day_emails) < max_per_day:
            for cid, state in sim_state.items():
                if len(day_emails) >= max_per_day:
                    break
                if state['status'] != 'pending' or not state['has_initial_draft']:
                    continue

                c = state['contact']
                initial_email = Email.query.filter_by(
                    contact_id=c.id, email_type='initial'
                ).first()
                day_emails.append({
                    'contact_name': c.name,
                    'company': c.company,
                    'contact_email': c.email,
                    'email_type': 'initial',
                    'subject': initial_email.subject if initial_email else '(initial)',
                    'wave': c.wave,
                    'email_confidence': c.email_confidence,
                })
                # Simulate: this contact is now "initial_sent" for future days
                state['status'] = 'initial_sent'
                state['initial_sent_date'] = sim_date
                state['has_initial_draft'] = False

        # Simulate follow-up state changes for emails we "sent" today
        for email_item in day_emails:
            for cid, state in sim_state.items():
                c = state['contact']
                if c.name == email_item['contact_name'] and c.company == email_item['company']:
                    if email_item['email_type'] == 'followup1':
                        state['fu1_sent'] = True
                        state['has_fu1_draft'] = False
                    elif email_item['email_type'] == 'followup2':
                        state['fu2_sent'] = True
                        state['has_fu2_draft'] = False
                    break

        schedule.append({
            'date': sim_date.isoformat(),
            'day_label': label,
            'count': len(day_emails),
            'emails': day_emails,
        })

    return schedule


def get_queue_status(campaign_id=None):
    """Get current queue status for display."""
    query = Email.query.filter(Email.status.in_(['scheduled', 'queued']))
    if campaign_id:
        query = query.join(Contact).filter(
            Contact.campaign_id == campaign_id
        )

    scheduled = query.order_by(Email.scheduled_at.asc()).all()
    return [
        {
            'id': e.id,
            'email_id': e.id,
            'contact_id': e.contact_id,
            'contact_name': e.contact.name,
            'company': e.contact.company,
            'email_type': e.email_type,
            'subject': e.subject,
            'body': e.body,
            'scheduled_at': (
                e.scheduled_at.isoformat() if e.scheduled_at else None
            ),
            'status': e.status,
        }
        for e in scheduled
    ]

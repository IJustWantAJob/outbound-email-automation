"""Report generation and viewing route handlers.

Generates and serves campaign reports: daily summaries,
weekly summaries, and final campaign reports.
"""

import os
from datetime import datetime, timezone, date

from flask import Blueprint, jsonify, request, send_file

from database import db
from models import Campaign, Contact, Email, Reply, Metric, Report

reports_bp = Blueprint('reports', __name__, url_prefix='/api/reports')

# Directory where generated report markdown files are stored
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'reports')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _report_to_dict(report, include_content=False):
    """Convert a Report model to a JSON-serializable dict."""
    d = {
        'id': report.id,
        'campaign_id': report.campaign_id,
        'report_type': report.report_type,
        'filename': report.filename,
        'generated_at': (
            report.generated_at.isoformat() if report.generated_at else None
        ),
    }
    if include_content:
        d['content'] = report.content
    return d


def _compute_response_time_hours(contact_id):
    """Compute response time in hours for a contact that replied.

    Returns the delta between the most recent sent email and the first reply,
    or None if not computable.
    """
    reply = Reply.query.filter_by(contact_id=contact_id).order_by(
        Reply.received_at.asc()
    ).first()
    if not reply or not reply.received_at:
        return None

    last_sent = Email.query.filter(
        Email.contact_id == contact_id,
        Email.status == 'sent',
        Email.sent_at.isnot(None),
    ).order_by(Email.sent_at.desc()).first()

    if not last_sent or not last_sent.sent_at:
        return None

    sent_at = last_sent.sent_at
    received_at = reply.received_at
    # Normalize timezone awareness
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    delta = received_at - sent_at
    return delta.total_seconds() / 3600


def _format_hours(hours):
    """Format hours into a human-readable string."""
    if hours is None:
        return 'N/A'
    if hours < 24:
        return f'{hours:.1f} hours'
    days = hours / 24
    return f'{days:.1f} days'


# ---------------------------------------------------------------------------
# Report generation functions
# ---------------------------------------------------------------------------

def generate_campaign_report(campaign_id, report_type='campaign_summary'):
    """Generate a full campaign report and store it in the DB and filesystem.

    Returns the created Report model instance.
    """
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError(f'Campaign {campaign_id} not found')

    contacts = Contact.query.filter_by(campaign_id=campaign_id).all()
    contact_ids = [c.id for c in contacts]

    now = datetime.now(timezone.utc)

    # --- Aggregate metrics ---
    total_contacts = len(contacts)

    sent_emails = Email.query.filter(
        Email.contact_id.in_(contact_ids),
        Email.status == 'sent',
    ).all() if contact_ids else []

    total_sent = len(sent_emails)

    # Count by email type
    initial_sent = sum(1 for e in sent_emails if e.email_type == 'initial')
    fu1_sent = sum(1 for e in sent_emails if e.email_type == 'followup1')
    fu2_sent = sum(1 for e in sent_emails if e.email_type == 'followup2')

    replies = Reply.query.filter(
        Reply.contact_id.in_(contact_ids)
    ).all() if contact_ids else []
    total_replied = len(replies)

    # Unique contacts that replied
    replied_contact_ids = set(r.contact_id for r in replies)

    response_rate = (
        len(replied_contact_ids) / initial_sent * 100
    ) if initial_sent > 0 else 0.0

    # Average response time
    response_times = []
    for cid in replied_contact_ids:
        hours = _compute_response_time_hours(cid)
        if hours is not None:
            response_times.append(hours)
    avg_response_hours = (
        sum(response_times) / len(response_times)
    ) if response_times else 0.0
    avg_response_days = avg_response_hours / 24 if avg_response_hours else 0.0

    # Bounced and opted out
    bounced_count = Metric.query.filter(
        Metric.contact_id.in_(contact_ids),
        Metric.metric_type == 'bounced',
    ).count() if contact_ids else 0

    opted_out = sum(1 for c in contacts if c.status == 'opted_out')

    # Still pending
    pending_count = sum(1 for c in contacts if c.status == 'pending')

    # --- Per-wave performance ---
    waves = sorted(set(c.wave for c in contacts if c.wave is not None))
    wave_rows = []
    for wave_num in waves:
        wave_contacts = [c for c in contacts if c.wave == wave_num]
        wave_cids = [c.id for c in wave_contacts]
        wave_sent_emails = [e for e in sent_emails if e.contact_id in wave_cids]
        wave_sent_count = len(wave_sent_emails)
        wave_replied_cids = replied_contact_ids & set(wave_cids)
        wave_replied_count = len(wave_replied_cids)
        wave_rate = (
            wave_replied_count / len(wave_contacts) * 100
        ) if wave_contacts else 0.0

        wave_times = []
        for cid in wave_replied_cids:
            h = _compute_response_time_hours(cid)
            if h is not None:
                wave_times.append(h)
        wave_avg_time = (
            sum(wave_times) / len(wave_times)
        ) if wave_times else 0.0

        wave_rows.append({
            'wave': wave_num,
            'contacts': len(wave_contacts),
            'sent': wave_sent_count,
            'replied': wave_replied_count,
            'rate': wave_rate,
            'avg_time': wave_avg_time,
        })

    # --- Contact status breakdown ---
    status_counts = {}
    for c in contacts:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1

    # --- Top responders (fastest replies) ---
    responders = []
    for cid in replied_contact_ids:
        contact = next((c for c in contacts if c.id == cid), None)
        if not contact:
            continue
        hours = _compute_response_time_hours(cid)
        reply = Reply.query.filter_by(contact_id=cid).order_by(
            Reply.received_at.asc()
        ).first()
        snippet = reply.snippet[:50] + '...' if reply and reply.snippet and len(reply.snippet) > 50 else (reply.snippet if reply else '')
        responders.append({
            'contact': contact.name,
            'company': contact.company or '',
            'hours': hours or 0,
            'snippet': snippet or '',
        })
    responders.sort(key=lambda x: x['hours'])

    # --- Contacts still waiting ---
    waiting_statuses = {'initial_sent', 'followup1_sent', 'followup2_sent'}
    waiting = []
    for c in contacts:
        if c.status not in waiting_statuses:
            continue
        last_email = Email.query.filter(
            Email.contact_id == c.id,
            Email.status == 'sent',
        ).order_by(Email.sent_at.desc()).first()
        days_since = 0
        if last_email and last_email.sent_at:
            sent_at = last_email.sent_at
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            delta = now - sent_at
            days_since = delta.total_seconds() / 86400
        waiting.append({
            'contact': c.name,
            'company': c.company or '',
            'status': c.status,
            'last_type': last_email.email_type if last_email else 'N/A',
            'days_since': days_since,
        })
    waiting.sort(key=lambda x: -x['days_since'])

    # --- Email performance by type ---
    email_types = ['initial', 'followup1', 'followup2']
    type_labels = {
        'initial': ('Initial', 'First touch'),
        'followup1': ('Follow-Up 1', 'Day 3-4 nudge'),
        'followup2': ('Follow-Up 2', 'Final ask'),
    }
    email_perf = []
    for etype in email_types:
        type_sent = [e for e in sent_emails if e.email_type == etype]
        type_sent_cids = set(e.contact_id for e in type_sent)

        # Count replies that came after this email type was the last sent
        type_reply_count = 0
        for cid in type_sent_cids:
            if cid in replied_contact_ids:
                # Check if this type was the last email sent before reply
                reply_obj = Reply.query.filter_by(contact_id=cid).order_by(
                    Reply.received_at.asc()
                ).first()
                if reply_obj:
                    last_before = Email.query.filter(
                        Email.contact_id == cid,
                        Email.status == 'sent',
                        Email.sent_at.isnot(None),
                        Email.sent_at <= reply_obj.received_at,
                    ).order_by(Email.sent_at.desc()).first()
                    if last_before and last_before.email_type == etype:
                        type_reply_count += 1

        type_rate = (
            type_reply_count / len(type_sent) * 100
        ) if type_sent else 0.0
        label, notes = type_labels.get(etype, (etype, ''))
        email_perf.append({
            'type': label,
            'sent': len(type_sent),
            'rate': type_rate,
            'notes': notes,
        })

    # --- Campaign notes ---
    notes_list = [
        f'**{c.name}** ({c.company}): {c.notes}'
        for c in contacts if c.notes
    ]

    # --- Auto-generated recommendations ---
    recommendations = _generate_recommendations(
        wave_rows, email_perf, pending_count,
        total_contacts, response_rate, responders, waiting,
    )

    # --- Build markdown ---
    lines = []
    lines.append(f'# Campaign Report: {campaign.name}')
    lines.append(f'Generated: {now.strftime("%Y-%m-%d %H:%M UTC")}')
    lines.append('')

    # Summary
    lines.append('## Summary')
    lines.append(f'- Total contacts: {total_contacts}')
    lines.append(
        f'- Emails sent: {total_sent} '
        f'(initial: {initial_sent}, follow-up 1: {fu1_sent}, follow-up 2: {fu2_sent})'
    )
    lines.append(f'- Replies received: {total_replied}')
    lines.append(f'- Response rate: {response_rate:.1f}%')
    lines.append(
        f'- Average response time: {avg_response_hours:.1f} hours '
        f'({avg_response_days:.1f} days)'
    )
    lines.append(f'- Bounced: {bounced_count}')
    lines.append(f'- Opted out: {opted_out}')
    lines.append(f'- Still pending: {pending_count}')
    lines.append('')

    # Per-wave performance
    if wave_rows:
        lines.append('## Per-Wave Performance')
        lines.append(
            '| Wave | Contacts | Sent | Replied | Response Rate | Avg Response Time |'
        )
        lines.append(
            '|------|----------|------|---------|---------------|-------------------|'
        )
        for w in wave_rows:
            lines.append(
                f'| {w["wave"]} | {w["contacts"]} | {w["sent"]} '
                f'| {w["replied"]} | {w["rate"]:.0f}% '
                f'| {_format_hours(w["avg_time"])} |'
            )
        lines.append('')

    # Contact status breakdown
    lines.append('## Contact Status Breakdown')
    lines.append('| Status | Count | Percentage |')
    lines.append('|--------|-------|------------|')
    for status, count in sorted(status_counts.items()):
        pct = count / total_contacts * 100 if total_contacts > 0 else 0
        lines.append(f'| {status} | {count} | {pct:.0f}% |')
    lines.append('')

    # Top responders
    if responders:
        lines.append('## Top Responders (Fastest Replies)')
        lines.append(
            '| # | Contact | Company | Response Time | Reply Snippet |'
        )
        lines.append(
            '|---|---------|---------|---------------|---------------|'
        )
        for i, r in enumerate(responders, 1):
            lines.append(
                f'| {i} | {r["contact"]} | {r["company"]} '
                f'| {_format_hours(r["hours"])} | "{r["snippet"]}" |'
            )
        lines.append('')

    # Contacts still waiting
    if waiting:
        lines.append('## Contacts Still Waiting')
        lines.append(
            '| # | Contact | Company | Status | Last Email | Days Since |'
        )
        lines.append(
            '|---|---------|---------|--------|------------|------------|'
        )
        for i, w in enumerate(waiting, 1):
            lines.append(
                f'| {i} | {w["contact"]} | {w["company"]} '
                f'| {w["status"]} | {w["last_type"]} '
                f'| {w["days_since"]:.0f} days |'
            )
        lines.append('')

    # Email performance by type
    lines.append('## Email Performance by Type')
    lines.append('| Type | Sent | Reply Rate | Notes |')
    lines.append('|------|------|------------|-------|')
    for ep in email_perf:
        lines.append(
            f'| {ep["type"]} | {ep["sent"]} | {ep["rate"]:.0f}% | {ep["notes"]} |'
        )
    lines.append('')

    # Campaign notes
    if notes_list:
        lines.append('## Campaign Notes')
        for note in notes_list:
            lines.append(f'- {note}')
        lines.append('')

    # Recommendations
    if recommendations:
        lines.append('## Recommendations')
        for rec in recommendations:
            lines.append(f'- {rec}')
        lines.append('')

    content = '\n'.join(lines)

    # --- Persist ---
    filename = (
        f'campaign_{campaign_id}_{report_type}'
        f'_{now.strftime("%Y%m%d_%H%M%S")}.md'
    )

    # Write to filesystem
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, 'w') as f:
        f.write(content)

    # Write to database
    report = Report(
        campaign_id=campaign_id,
        report_type=report_type,
        filename=filename,
        content=content,
        generated_at=now,
    )
    db.session.add(report)
    db.session.commit()

    return report


def generate_daily_summary(campaign_id):
    """Generate a daily summary report for a campaign.

    Returns the created Report model instance.
    """
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError(f'Campaign {campaign_id} not found')

    contacts = Contact.query.filter_by(campaign_id=campaign_id).all()
    contact_ids = [c.id for c in contacts]

    now = datetime.now(timezone.utc)
    today = now.date()

    # Today's sent emails
    sent_today = Email.query.filter(
        Email.contact_id.in_(contact_ids),
        Email.status == 'sent',
        Email.sent_at.isnot(None),
        db.func.date(Email.sent_at) == today,
    ).order_by(Email.sent_at.asc()).all() if contact_ids else []

    # Today's replies
    replies_today = Reply.query.filter(
        Reply.contact_id.in_(contact_ids),
        db.func.date(Reply.received_at) == today,
    ).order_by(Reply.received_at.asc()).all() if contact_ids else []

    # Follow-ups cancelled today (via metric or email status)
    cancelled_today = Email.query.filter(
        Email.contact_id.in_(contact_ids),
        Email.status == 'cancelled',
        Email.email_type.in_(['followup1', 'followup2']),
    ).count() if contact_ids else 0

    # Tomorrow's queue
    tomorrow_queue = Email.query.filter(
        Email.contact_id.in_(contact_ids),
        Email.status.in_(['scheduled', 'draft']),
    ).order_by(Email.scheduled_at.asc()).limit(20).all() if contact_ids else []

    # --- Build markdown ---
    lines = []
    lines.append(f'# Daily Summary: {campaign.name}')
    lines.append(f'Date: {today.isoformat()}')
    lines.append('')

    lines.append("## Today's Activity")
    lines.append(f'- Emails sent: {len(sent_today)}')
    lines.append(f'- Replies received: {len(replies_today)}')
    lines.append(f'- Follow-ups cancelled (reply detected): {cancelled_today}')
    lines.append('')

    # Sent today
    if sent_today:
        lines.append('## Sent Today')
        lines.append('| Time | Contact | Company | Type | Subject |')
        lines.append('|------|---------|---------|------|---------|')
        for e in sent_today:
            contact = next((c for c in contacts if c.id == e.contact_id), None)
            time_str = (
                e.sent_at.strftime('%H:%M') if e.sent_at else 'N/A'
            )
            lines.append(
                f'| {time_str} '
                f'| {contact.name if contact else "Unknown"} '
                f'| {contact.company if contact else ""} '
                f'| {e.email_type} | {e.subject} |'
            )
        lines.append('')

    # Replies today
    if replies_today:
        lines.append('## Replies Today')
        lines.append('| Contact | Company | Response Time | Snippet |')
        lines.append('|---------|---------|---------------|---------|')
        for r in replies_today:
            contact = next(
                (c for c in contacts if c.id == r.contact_id), None
            )
            hours = _compute_response_time_hours(r.contact_id)
            snippet = r.snippet[:50] + '...' if r.snippet and len(r.snippet) > 50 else (r.snippet or '')
            lines.append(
                f'| {contact.name if contact else "Unknown"} '
                f'| {contact.company if contact else ""} '
                f'| {_format_hours(hours)} | "{snippet}" |'
            )
        lines.append('')

    # Tomorrow's queue
    if tomorrow_queue:
        lines.append("## Tomorrow's Queue")
        lines.append('| Time | Contact | Company | Type |')
        lines.append('|------|---------|---------|------|')
        for e in tomorrow_queue:
            contact = next(
                (c for c in contacts if c.id == e.contact_id), None
            )
            time_str = (
                e.scheduled_at.strftime('%H:%M') if e.scheduled_at else 'TBD'
            )
            lines.append(
                f'| {time_str} '
                f'| {contact.name if contact else "Unknown"} '
                f'| {contact.company if contact else ""} '
                f'| {e.email_type} |'
            )
        lines.append('')

    content = '\n'.join(lines)

    # --- Persist ---
    filename = (
        f'daily_{campaign_id}_{today.isoformat()}.md'
    )

    os.makedirs(REPORTS_DIR, exist_ok=True)
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, 'w') as f:
        f.write(content)

    report = Report(
        campaign_id=campaign_id,
        report_type='daily_summary',
        filename=filename,
        content=content,
        generated_at=now,
    )
    db.session.add(report)
    db.session.commit()

    return report


def _generate_recommendations(
    wave_rows, email_perf, pending_count,
    total_contacts, response_rate, responders, waiting,
):
    """Auto-generate recommendations based on campaign data."""
    recs = []

    # Best wave
    if wave_rows:
        best_wave = max(wave_rows, key=lambda w: w['rate'])
        if best_wave['rate'] > 0:
            recs.append(
                f'Wave {best_wave["wave"]} has highest response rate '
                f'({best_wave["rate"]:.0f}%) '
                f'-- consider adding more similar contacts'
            )

    # Most effective email type
    effective_types = [ep for ep in email_perf if ep['sent'] > 0 and ep['rate'] > 0]
    if effective_types:
        best_type = max(effective_types, key=lambda x: x['rate'])
        recs.append(
            f'{best_type["type"]} is most effective '
            f'({best_type["rate"]:.0f}% reply rate)'
        )

    # Unreached contacts
    if pending_count > 0:
        recs.append(
            f'{pending_count} contacts haven\'t been reached yet '
            f'-- schedule remaining initials'
        )

    # Low response rate warning
    if response_rate < 10 and total_contacts > 5:
        recs.append(
            'Response rate is below 10% -- consider revising email copy '
            'or targeting criteria'
        )

    # Stale waiting contacts
    stale = [w for w in waiting if w['days_since'] > 7]
    if stale:
        recs.append(
            f'{len(stale)} contacts have been waiting 7+ days with no reply '
            f'-- consider phone/LinkedIn outreach'
        )

    return recs


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@reports_bp.route('/generate', methods=['POST'])
def api_generate_report():
    """Generate a campaign report."""
    data = request.get_json()
    if not data or not data.get('campaign_id'):
        return jsonify({'error': 'campaign_id is required'}), 400

    campaign_id = data['campaign_id']
    report_type = data.get('report_type', 'campaign_summary')

    try:
        if report_type == 'daily_summary':
            report = generate_daily_summary(campaign_id)
        else:
            report = generate_campaign_report(campaign_id, report_type)
        return jsonify(_report_to_dict(report, include_content=True)), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': f'Report generation failed: {str(e)}'}), 500


@reports_bp.route('', methods=['GET'])
def api_list_reports():
    """List all generated reports."""
    campaign_id = request.args.get('campaign_id', type=int)
    query = Report.query

    if campaign_id is not None:
        query = query.filter_by(campaign_id=campaign_id)

    reports = query.order_by(Report.generated_at.desc()).all()
    return jsonify([_report_to_dict(r) for r in reports])


@reports_bp.route('/<int:report_id>', methods=['GET'])
def api_get_report(report_id):
    """Get a report by ID including its content."""
    report = db.session.get(Report, report_id)
    if not report:
        return jsonify({'error': 'Report not found'}), 404
    return jsonify(_report_to_dict(report, include_content=True))


@reports_bp.route('/<int:report_id>/download', methods=['GET'])
def api_download_report(report_id):
    """Download a report as a markdown file."""
    report = db.session.get(Report, report_id)
    if not report:
        return jsonify({'error': 'Report not found'}), 404

    if report.filename:
        filepath = os.path.join(REPORTS_DIR, report.filename)
        if os.path.exists(filepath):
            return send_file(
                filepath,
                mimetype='text/markdown',
                as_attachment=True,
                download_name=report.filename,
            )

    # Fallback: serve content from DB
    if report.content:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        tmp.write(report.content)
        tmp.close()
        filename = report.filename or f'report_{report.id}.md'
        return send_file(
            tmp.name,
            mimetype='text/markdown',
            as_attachment=True,
            download_name=filename,
        )

    return jsonify({'error': 'Report content not available'}), 404

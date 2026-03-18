"""Detect replies to campaign emails by scanning Gmail threads."""

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from gmail.auth import gmail_auth
from database import db
from models import Contact, Email, Reply, Metric


def check_for_replies():
    """
    Scan Gmail threads for replies to sent campaign emails.

    For each sent email with a gmail_thread_id:
    1. Skip if we already detected a reply for this thread
    2. Fetch the thread from Gmail API
    3. Check if any message is FROM someone other than us
    4. If so: create Reply record, update Contact status to 'replied',
       cancel all pending/scheduled follow-ups for that contact

    Returns: list of (contact_id, reply_snippet) tuples for new replies found
    """
    service = gmail_auth.get_service()
    our_email = gmail_auth.get_connected_email()

    if not our_email:
        return []

    new_replies = []

    # Get all unique thread IDs from sent emails
    sent_threads = (
        db.session.query(Email.gmail_thread_id, Email.contact_id)
        .filter(
            Email.gmail_thread_id.isnot(None),
            Email.status == 'sent',
        )
        .distinct()
        .all()
    )

    for thread_id, contact_id in sent_threads:
        # Skip if reply already detected for this contact/thread
        existing = Reply.query.filter_by(
            contact_id=contact_id,
            gmail_thread_id=thread_id,
        ).first()
        if existing:
            continue

        try:
            thread = service.users().threads().get(
                userId='me',
                id=thread_id,
                format='metadata',
                metadataHeaders=['From', 'Subject', 'Date'],
            ).execute()
        except Exception:
            continue

        messages = thread.get('messages', [])
        if len(messages) <= 1:
            continue  # Only our sent message(s), no external reply

        for msg in messages:
            headers = {
                h['name'].lower(): h['value']
                for h in msg['payload'].get('headers', [])
            }
            from_addr = headers.get('from', '')

            # Skip our own messages
            if our_email.lower() in from_addr.lower():
                continue

            # This is an external reply
            contact = db.session.get(Contact, contact_id)
            if not contact:
                continue

            # Extract email from "Name <email>" format
            reply_email = _extract_email(from_addr)

            # Parse date
            received_at = _parse_gmail_date(headers.get('date', ''))

            reply = Reply(
                contact_id=contact.id,
                gmail_message_id=msg['id'],
                gmail_thread_id=thread_id,
                from_email=reply_email or from_addr,
                subject=headers.get('subject', ''),
                snippet=msg.get('snippet', '')[:500],
                received_at=received_at or datetime.now(timezone.utc),
            )
            db.session.add(reply)

            # Update contact status
            contact.status = 'replied'

            # Cancel all pending/scheduled follow-ups for this contact
            Email.query.filter(
                Email.contact_id == contact.id,
                Email.status.in_(['draft', 'queued', 'scheduled']),
            ).update({'status': 'cancelled'}, synchronize_session='fetch')

            # Record metric
            metric = Metric(
                contact_id=contact.id,
                metric_type='replied',
                value=msg.get('snippet', '')[:200],
            )
            db.session.add(metric)

            db.session.commit()
            new_replies.append((contact.id, msg.get('snippet', '')))
            break  # Only process first external reply per thread

    return new_replies


def _extract_email(from_header):
    """Extract email address from 'Name <email@example.com>' format."""
    match = re.search(r'<([^>]+)>', from_header)
    if match:
        return match.group(1)
    # Maybe it's just an email address
    if '@' in from_header:
        return from_header.strip()
    return None


def _parse_gmail_date(date_str):
    """Parse Gmail date header into datetime."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None

"""Send emails via Gmail API."""

import base64
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

from gmail.auth import gmail_auth
from database import db
from models import Email, Metric


def _strip_signoff(text):
    """Remove trailing sign-offs like 'Best, [Name]' since the Gmail signature handles it."""
    # Match common sign-offs at the end of the body (name must start with uppercase)
    pattern = r'\n{1,3}(Best|Sincerely|Thanks|Thank you|Cheers|Regards|Best regards|Warm regards|All the best),?\s*\n\s*[A-Z]\w*\s*$'
    return re.sub(pattern, '', text, flags=re.IGNORECASE)


def _clean_body(text):
    """Strip \\r, trailing whitespace per line, collapse excess blank lines, remove sign-offs."""
    lines = text.replace('\r', '').split('\n')
    lines = [line.rstrip() for line in lines]
    cleaned = '\n'.join(lines).strip()
    return _strip_signoff(cleaned)


def _body_to_html(text):
    """Convert plain text body to clean HTML paragraphs."""
    text = _clean_body(text)
    paragraphs = text.split('\n\n')
    html_parts = []
    for para in paragraphs:
        para_html = '<br>\n'.join(para.split('\n'))
        html_parts.append(f'<p style="margin:0 0 12px 0;">{para_html}</p>')
    return '\n'.join(html_parts)


def _get_gmail_signature(service):
    """Fetch the user's Gmail signature via the API.

    Returns:
        HTML signature string, or empty string if none set.
    """
    try:
        sendas = service.users().settings().sendAs().list(userId='me').execute()
        for alias in sendas.get('sendAs', []):
            if alias.get('isDefault'):
                return alias.get('signature', '')
        return ''
    except Exception:
        return ''


def _signature_html_to_plain(html_sig):
    """Convert HTML signature to a rough plain text version."""
    if not html_sig:
        return ''
    text = html_sig
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'</?p[^>]*>', '\n', text)
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>[^<]*</a>', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&middot;', '·', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return '\n--\n' + text.strip()


def send_email(email_record):
    """
    Send a single Email record via Gmail API.

    Args:
        email_record: Email model instance with subject, body, contact relationship

    Returns:
        (gmail_message_id, gmail_thread_id) tuple

    Updates the email_record status to 'sent' on success or 'failed' on error.
    Creates a Metric record on success.
    """
    service = gmail_auth.get_service()
    contact = email_record.contact

    clean_body = _clean_body(email_record.body)

    # Fetch the user's actual Gmail signature
    sig_html = _get_gmail_signature(service)
    sig_plain = _signature_html_to_plain(sig_html)

    # Build MIME message
    message = MIMEMultipart('alternative')
    message['to'] = contact.email
    message['subject'] = email_record.subject

    # Plain text version — single blank line before signature
    message.attach(MIMEText(clean_body + '\n' + sig_plain, 'plain'))

    # HTML version — single <br> before signature
    html_body = _body_to_html(email_record.body)
    sig_block = f'<br><div class="gmail_signature">{sig_html}</div>' if sig_html else ''
    html = f'<html><body style="font-family:Arial,sans-serif; font-size:14px; color:#222;">{html_body}{sig_block}</body></html>'
    message.attach(MIMEText(html, 'html'))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {'raw': raw}

    # Thread follow-ups in the same Gmail thread
    if email_record.email_type in ('followup1', 'followup2'):
        initial = Email.query.filter_by(
            contact_id=email_record.contact_id,
            email_type='initial',
            status='sent',
        ).first()
        if initial and initial.gmail_thread_id:
            body['threadId'] = initial.gmail_thread_id

    try:
        sent = service.users().messages().send(
            userId='me', body=body
        ).execute()

        email_record.gmail_message_id = sent['id']
        email_record.gmail_thread_id = sent.get('threadId', sent['id'])
        email_record.status = 'sent'
        email_record.sent_at = datetime.now(timezone.utc)

        # Update contact status
        status_map = {
            'initial': 'initial_sent',
            'followup1': 'followup1_sent',
            'followup2': 'followup2_sent',
        }
        if email_record.email_type in status_map:
            contact.status = status_map[email_record.email_type]

        # Record metric
        metric = Metric(
            contact_id=contact.id,
            metric_type='sent',
            value=email_record.email_type,
        )
        db.session.add(metric)
        db.session.commit()

        return sent['id'], sent.get('threadId', sent['id'])

    except Exception as e:
        email_record.status = 'failed'
        email_record.error_message = str(e)[:500]
        db.session.commit()
        raise


def send_test_email(
    to_email,
    subject='Campaign Manager - Test Email',
    body='This is a test email from your campaign manager. If you received this, your Gmail connection is working correctly.',
    include_signature=True,
):
    """Send a quick test email to verify Gmail connection works."""
    service = gmail_auth.get_service()

    clean_body = _clean_body(body)

    # Fetch the user's actual Gmail signature
    sig_html = ''
    sig_plain = ''
    if include_signature:
        sig_html = _get_gmail_signature(service)
        sig_plain = _signature_html_to_plain(sig_html)

    message = MIMEMultipart('alternative')
    message['to'] = to_email
    message['subject'] = subject

    # Plain text — single blank line before signature
    message.attach(MIMEText(clean_body + '\n' + sig_plain, 'plain'))

    # HTML — single <br> before signature
    html_body = _body_to_html(body)
    sig_block = f'<br><div class="gmail_signature">{sig_html}</div>' if sig_html else ''
    html = f'<html><body style="font-family:Arial,sans-serif; font-size:14px; color:#222;">{html_body}{sig_block}</body></html>'
    message.attach(MIMEText(html, 'html'))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = service.users().messages().send(
        userId='me', body={'raw': raw}
    ).execute()
    return sent['id']

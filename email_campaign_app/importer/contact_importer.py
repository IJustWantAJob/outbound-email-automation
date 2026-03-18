"""Contact importer — loads parsed markdown data into the database.

Takes the output of markdown_parser.parse_campaign_markdown() and creates
Campaign, Contact, and Email records.
"""

from database import db
from models import Campaign, Contact, Email


def import_contacts(parsed_contacts, campaign_id=None):
    """Import parsed contacts into the database.

    Takes a list of parsed contact dicts (from parse_campaign_markdown +
    optional enrich_contacts), creates a Campaign (if needed), Contact
    records, and Email records (initial + followup1 + followup2).

    Skips DROPPED contacts entirely.
    For NEEDS LINKEDIN contacts: creates Contact with
    needs_linkedin_verification=True and status='pending', creates Email
    records with whatever content is available.

    Idempotent: if a contact with the same external_id already exists in
    the campaign, it is skipped (not duplicated).

    Args:
        parsed_contacts: List of dicts from parse_campaign_markdown().
        campaign_id: Optional existing Campaign.id. If None, a new
            campaign is created.

    Returns:
        Tuple of (num_contacts_created, num_emails_created, num_skipped).
    """
    # Get or create campaign
    if campaign_id is not None:
        campaign = db.session.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign with id={campaign_id} not found")
    else:
        campaign = Campaign(
            name='Imported Campaign',
            description='Imported from campaign markdown file',
            status='draft',
        )
        db.session.add(campaign)
        db.session.flush()  # Get the campaign.id

    # Check which external_ids already exist in this campaign
    existing_ext_ids = set()
    existing_contacts = Contact.query.filter_by(
        campaign_id=campaign.id
    ).all()
    for c in existing_contacts:
        if c.external_id:
            existing_ext_ids.add(str(c.external_id))

    num_contacts_created = 0
    num_emails_created = 0
    num_skipped = 0

    for pc in parsed_contacts:
        ext_id = str(pc['external_id'])

        # Skip dropped contacts
        if pc.get('is_dropped', False):
            num_skipped += 1
            continue

        # Skip if already imported (idempotency)
        if ext_id in existing_ext_ids:
            num_skipped += 1
            continue

        # Determine contact status
        if pc.get('needs_linkedin', False):
            contact_status = 'pending'
        else:
            contact_status = 'pending'

        # Build the contact name
        name = pc.get('name', '')
        if not name:
            # Fallback: try to extract from email greeting
            name = _extract_name_from_body(pc.get('initial_body', ''))
        if not name:
            # Last resort: use company name as placeholder
            name = f"Contact at {pc['company']}"

        # Map email confidence
        email_confidence = pc.get('email_confidence', '')
        if email_confidence not in ('HIGH', 'MEDIUM', 'LOW', ''):
            email_confidence = ''

        # Create Contact
        contact = Contact(
            campaign_id=campaign.id,
            external_id=ext_id,
            company=pc.get('company', ''),
            name=name,
            title=pc.get('title', ''),
            email=pc.get('email', '') or '',
            email_confidence=email_confidence or None,
            response_likelihood=pc.get('response_likelihood', 0) or None,
            wave=pc.get('wave', None),
            ask_type=pc.get('ask_type', '') or None,
            status=contact_status,
            needs_linkedin_verification=pc.get('needs_linkedin', False),
            personalization_hooks=pc.get('personalization_hooks') or None,
            notes=pc.get('status_raw', ''),
        )
        db.session.add(contact)
        db.session.flush()  # Get the contact.id

        num_contacts_created += 1

        # Create Email records (initial, followup1, followup2)
        emails_to_create = [
            {
                'email_type': 'initial',
                'subject': pc.get('initial_subject', ''),
                'body': pc.get('initial_body', ''),
            },
            {
                'email_type': 'followup1',
                'subject': pc.get('followup1_subject', ''),
                'body': pc.get('followup1_body', ''),
            },
            {
                'email_type': 'followup2',
                'subject': pc.get('followup2_subject', ''),
                'body': pc.get('followup2_body', ''),
            },
        ]

        for email_data in emails_to_create:
            subject = email_data['subject'] or '(no subject)'
            body = email_data['body'] or '(no content - needs writing)'

            email_record = Email(
                contact_id=contact.id,
                email_type=email_data['email_type'],
                subject=subject,
                body=body,
                status='draft',
            )
            db.session.add(email_record)
            num_emails_created += 1

    db.session.commit()

    return num_contacts_created, num_emails_created, num_skipped


def _extract_name_from_body(body):
    """Try to extract the recipient's first name from the email body greeting.

    Returns the name string, or empty string if not found.
    """
    if not body:
        return ''

    import re
    match = re.match(r'^Hi\s+(.+?)[,\s]', body)
    if match:
        name = match.group(1).strip()
        if name == '[First Name]':
            return ''
        return name
    return ''

"""REST API route handlers.

JSON API endpoints for campaign management, contact operations,
email status queries, and scheduler control.
"""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from database import db
from models import Campaign, Contact, Email, Reply, Metric, SenderProfile, ApiKey

api_bp = Blueprint('api', __name__, url_prefix='/api')


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def campaign_to_dict(campaign):
    """Convert a Campaign model to a JSON-serializable dict."""
    return {
        'id': campaign.id,
        'name': campaign.name,
        'description': campaign.description,
        'status': campaign.status,
        'send_start_hour': campaign.send_start_hour,
        'send_end_hour': campaign.send_end_hour,
        'min_interval_minutes': campaign.min_interval_minutes,
        'max_emails_per_day': campaign.max_emails_per_day,
        'followup1_delay_days': campaign.followup1_delay_days,
        'followup2_delay_days': campaign.followup2_delay_days,
        'timezone': campaign.timezone,
        'created_at': campaign.created_at.isoformat() if campaign.created_at else None,
        'updated_at': campaign.updated_at.isoformat() if campaign.updated_at else None,
    }


def contact_to_dict(contact, include_emails=False, include_replies=False):
    """Convert a Contact model to a JSON-serializable dict."""
    d = {
        'id': contact.id,
        'campaign_id': contact.campaign_id,
        'external_id': contact.external_id,
        'company': contact.company,
        'name': contact.name,
        'title': contact.title,
        'email': contact.email,
        'email_confidence': contact.email_confidence,
        'response_likelihood': contact.response_likelihood,
        'wave': contact.wave,
        'ask_type': contact.ask_type,
        'status': contact.status,
        'personalization_hooks': contact.personalization_hooks,
        'notes': contact.notes,
        'linkedin_url': contact.linkedin_url,
        'needs_linkedin_verification': contact.needs_linkedin_verification,
        'created_at': contact.created_at.isoformat() if contact.created_at else None,
        'updated_at': contact.updated_at.isoformat() if contact.updated_at else None,
    }
    if include_emails:
        d['emails'] = [email_to_dict(e) for e in contact.emails]
    if include_replies:
        d['replies'] = [reply_to_dict(r) for r in contact.replies]
    return d


def email_to_dict(email):
    """Convert an Email model to a JSON-serializable dict."""
    return {
        'id': email.id,
        'contact_id': email.contact_id,
        'email_type': email.email_type,
        'subject': email.subject,
        'body': email.body,
        'status': email.status,
        'scheduled_at': email.scheduled_at.isoformat() if email.scheduled_at else None,
        'sent_at': email.sent_at.isoformat() if email.sent_at else None,
        'gmail_message_id': email.gmail_message_id,
        'gmail_thread_id': email.gmail_thread_id,
        'error_message': email.error_message,
        'created_at': email.created_at.isoformat() if email.created_at else None,
    }


def reply_to_dict(reply):
    """Convert a Reply model to a JSON-serializable dict."""
    return {
        'id': reply.id,
        'contact_id': reply.contact_id,
        'email_id': reply.email_id,
        'gmail_message_id': reply.gmail_message_id,
        'gmail_thread_id': reply.gmail_thread_id,
        'from_email': reply.from_email,
        'subject': reply.subject,
        'snippet': reply.snippet,
        'received_at': reply.received_at.isoformat() if reply.received_at else None,
        'detected_at': reply.detected_at.isoformat() if reply.detected_at else None,
    }


def profile_to_dict(profile):
    """Convert a SenderProfile model to a JSON-serializable dict."""
    return {
        'id': profile.id,
        'company_name': profile.company_name,
        'company_description': profile.company_description,
        'industry': profile.industry,
        'product_description': profile.product_description,
        'sender_name': profile.sender_name,
        'sender_title': profile.sender_title,
        'sender_email': profile.sender_email,
        'sender_background': profile.sender_background,
        'linkedin_url': profile.linkedin_url,
        'university': profile.university,
        'accelerator': profile.accelerator,
        'target_customer_description': profile.target_customer_description,
        'target_segments': profile.target_segments,
        'geography': profile.geography,
        'tone_voice': profile.tone_voice,
        'key_metrics': profile.key_metrics,
        'pricing_notes': profile.pricing_notes,
        'created_at': profile.created_at.isoformat() if profile.created_at else None,
        'updated_at': profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _export_profile_for_nightly(profile):
    """Write profile.json + scaffold campaign folders from the profile."""
    from scaffolder import scaffold_campaigns
    data = profile_to_dict(profile)
    scaffold_campaigns(data)


# ---------------------------------------------------------------------------
# Sender Profile endpoints
# ---------------------------------------------------------------------------

@api_bp.route('/profile', methods=['GET'])
def get_profile():
    """Return the sender profile, or {exists: false} if none exists."""
    profile = SenderProfile.query.first()
    if not profile:
        return jsonify({'exists': False})
    data = profile_to_dict(profile)
    data['exists'] = True
    return jsonify(data)


@api_bp.route('/profile', methods=['POST'])
def create_profile():
    """Create the sender profile (onboarding)."""
    existing = SenderProfile.query.first()
    if existing:
        return jsonify({'error': 'Profile already exists. Use PUT to update.'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    if not data.get('company_name'):
        return jsonify({'error': 'company_name is required'}), 400
    if not data.get('sender_name'):
        return jsonify({'error': 'sender_name is required'}), 400

    profile = SenderProfile(
        company_name=data['company_name'],
        company_description=data.get('company_description', ''),
        industry=data.get('industry', ''),
        product_description=data.get('product_description', ''),
        sender_name=data['sender_name'],
        sender_title=data.get('sender_title', ''),
        sender_email=data.get('sender_email', ''),
        sender_background=data.get('sender_background', ''),
        linkedin_url=data.get('linkedin_url', ''),
        university=data.get('university', ''),
        accelerator=data.get('accelerator', ''),
        target_customer_description=data.get('target_customer_description', ''),
        target_segments=data.get('target_segments'),
        geography=data.get('geography', ''),
        tone_voice=data.get('tone_voice', 'Curious, respectful, not salesy'),
        key_metrics=data.get('key_metrics', ''),
        pricing_notes=data.get('pricing_notes', ''),
    )
    db.session.add(profile)
    db.session.commit()

    _export_profile_for_nightly(profile)

    result = profile_to_dict(profile)
    result['exists'] = True
    return jsonify(result), 201


@api_bp.route('/profile/rendered-prompt', methods=['GET'])
def get_rendered_prompt():
    """Return the NIGHTLY_PROMPT.md with profile data substituted."""
    profile = SenderProfile.query.first()
    if not profile:
        return jsonify({'error': 'No profile configured. Complete onboarding first.'}), 400
    from prompt_renderer import render_nightly_prompt
    rendered = render_nightly_prompt(profile_to_dict(profile))
    return jsonify({'prompt': rendered})


@api_bp.route('/profile', methods=['PUT'])
def update_profile():
    """Update the existing sender profile."""
    profile = SenderProfile.query.first()
    if not profile:
        return jsonify({'error': 'No profile exists. Use POST to create one.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    updatable = [
        'company_name', 'company_description', 'industry', 'product_description',
        'sender_name', 'sender_title', 'sender_email', 'sender_background',
        'linkedin_url', 'university', 'accelerator',
        'target_customer_description', 'target_segments', 'geography',
        'tone_voice', 'key_metrics', 'pricing_notes',
    ]
    for field in updatable:
        if field in data:
            setattr(profile, field, data[field])

    db.session.commit()

    _export_profile_for_nightly(profile)

    result = profile_to_dict(profile)
    result['exists'] = True
    return jsonify(result)


# ---------------------------------------------------------------------------
# API Key endpoints
# ---------------------------------------------------------------------------

def _get_fernet():
    """Get the Fernet instance for encrypting/decrypting API keys."""
    from flask import current_app
    from cryptography.fernet import Fernet
    fernet_key = current_app.config.get('FERNET_KEY', '')
    if fernet_key:
        return Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
    return None


@api_bp.route('/api-keys', methods=['GET'])
def get_api_keys():
    """Return configured API keys (masked) and their status."""
    keys = ApiKey.query.all()
    result = {}
    for k in keys:
        result[k.provider] = {
            'configured': True,
            'is_active': k.is_active,
            'updated_at': k.updated_at.isoformat() if k.updated_at else None,
        }
    # Always include anthropic even if not configured
    if 'anthropic' not in result:
        result['anthropic'] = {'configured': False, 'is_active': False}
    return jsonify(result)


@api_bp.route('/api-keys/<provider>', methods=['POST'])
def save_api_key(provider):
    """Save (or update) an API key for a provider."""
    if provider not in ('anthropic',):
        return jsonify({'error': f'Unknown provider: {provider}'}), 400

    data = request.get_json()
    if not data or not data.get('key'):
        return jsonify({'error': 'key is required'}), 400

    raw_key = data['key'].strip()
    fernet = _get_fernet()
    encrypted = fernet.encrypt(raw_key.encode()).decode() if fernet else raw_key

    existing = ApiKey.query.filter_by(provider=provider).first()
    if existing:
        existing.encrypted_key = encrypted
        existing.is_active = True
    else:
        existing = ApiKey(provider=provider, encrypted_key=encrypted, is_active=True)
        db.session.add(existing)

    db.session.commit()

    # Write to nightly/.env for shell scripts
    _export_api_key_for_nightly(provider, raw_key)

    return jsonify({'status': 'saved', 'provider': provider})


@api_bp.route('/api-keys/<provider>', methods=['DELETE'])
def delete_api_key(provider):
    """Deactivate an API key."""
    existing = ApiKey.query.filter_by(provider=provider).first()
    if existing:
        existing.is_active = False
        db.session.commit()
    return jsonify({'status': 'deactivated', 'provider': provider})


def _export_api_key_for_nightly(provider, raw_key):
    """Write API key to nightly/.env so shell scripts can source it."""
    import os
    nightly_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'nightly',
    )
    if not os.path.isdir(nightly_dir):
        return
    env_path = os.path.join(nightly_dir, '.env')
    env_vars = {}
    # Read existing .env
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env_vars[k] = v
    # Update
    var_name = {'anthropic': 'ANTHROPIC_API_KEY'}.get(provider)
    if var_name:
        env_vars[var_name] = raw_key
    # Write back
    with open(env_path, 'w') as f:
        for k, v in env_vars.items():
            f.write(f'{k}={v}\n')


# ---------------------------------------------------------------------------
# Campaign endpoints
# ---------------------------------------------------------------------------

@api_bp.route('/campaigns', methods=['GET'])
def list_campaigns():
    """List all campaigns."""
    campaigns = Campaign.query.order_by(Campaign.created_at.desc()).all()
    return jsonify([campaign_to_dict(c) for c in campaigns])


@api_bp.route('/campaigns', methods=['POST'])
def create_campaign():
    """Create a new campaign from JSON body."""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    campaign = Campaign(
        name=data['name'],
        description=data.get('description', ''),
        status=data.get('status', 'draft'),
        send_start_hour=data.get('send_start_hour', 8),
        send_end_hour=data.get('send_end_hour', 17),
        min_interval_minutes=data.get('min_interval_minutes', 15),
        max_emails_per_day=data.get('max_emails_per_day', 10),
        followup1_delay_days=data.get('followup1_delay_days', 3),
        followup2_delay_days=data.get('followup2_delay_days', 7),
        timezone=data.get('timezone', 'America/Los_Angeles'),
    )
    db.session.add(campaign)
    db.session.commit()
    return jsonify(campaign_to_dict(campaign)), 201


@api_bp.route('/campaigns/<int:campaign_id>', methods=['GET'])
def get_campaign(campaign_id):
    """Get a single campaign by ID."""
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return jsonify({'error': 'Campaign not found'}), 404
    return jsonify(campaign_to_dict(campaign))


@api_bp.route('/campaigns/<int:campaign_id>', methods=['PUT'])
def update_campaign(campaign_id):
    """Update campaign settings."""
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return jsonify({'error': 'Campaign not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    updatable = [
        'name', 'description', 'send_start_hour', 'send_end_hour',
        'min_interval_minutes', 'max_emails_per_day',
        'followup1_delay_days', 'followup2_delay_days', 'timezone',
    ]
    for field in updatable:
        if field in data:
            setattr(campaign, field, data[field])

    db.session.commit()
    return jsonify(campaign_to_dict(campaign))


@api_bp.route('/campaigns/<int:campaign_id>/activate', methods=['POST'])
def activate_campaign(campaign_id):
    """Set campaign status to active."""
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return jsonify({'error': 'Campaign not found'}), 404
    campaign.status = 'active'
    db.session.commit()
    return jsonify(campaign_to_dict(campaign))


@api_bp.route('/campaigns/<int:campaign_id>/pause', methods=['POST'])
def pause_campaign(campaign_id):
    """Set campaign status to paused."""
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return jsonify({'error': 'Campaign not found'}), 404
    campaign.status = 'paused'
    db.session.commit()
    return jsonify(campaign_to_dict(campaign))


@api_bp.route('/campaigns/<int:campaign_id>/metrics', methods=['GET'])
def campaign_metrics(campaign_id):
    """Aggregate metrics for a campaign."""
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return jsonify({'error': 'Campaign not found'}), 404

    contacts = Contact.query.filter_by(campaign_id=campaign_id).all()
    contact_ids = [c.id for c in contacts]

    total_contacts = len(contacts)
    total_sent = Email.query.filter(
        Email.contact_id.in_(contact_ids),
        Email.status == 'sent',
    ).count() if contact_ids else 0
    total_replied = Reply.query.filter(
        Reply.contact_id.in_(contact_ids),
    ).count() if contact_ids else 0
    total_bounced = Metric.query.filter(
        Metric.contact_id.in_(contact_ids),
        Metric.metric_type == 'bounced',
    ).count() if contact_ids else 0

    response_rate = (total_replied / total_sent * 100) if total_sent > 0 else 0.0

    return jsonify({
        'campaign_id': campaign_id,
        'total_contacts': total_contacts,
        'total_sent': total_sent,
        'total_replied': total_replied,
        'total_bounced': total_bounced,
        'response_rate': round(response_rate, 1),
    })


# ---------------------------------------------------------------------------
# Contact endpoints
# ---------------------------------------------------------------------------

@api_bp.route('/contacts', methods=['GET'])
def list_contacts():
    """List contacts with optional filters and pagination."""
    query = Contact.query

    # Filters
    campaign_id = request.args.get('campaign_id', type=int)
    if campaign_id is not None:
        query = query.filter_by(campaign_id=campaign_id)

    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)

    wave = request.args.get('wave', type=int)
    if wave is not None:
        query = query.filter_by(wave=wave)

    search = request.args.get('search')
    if search:
        like_pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                Contact.name.ilike(like_pattern),
                Contact.company.ilike(like_pattern),
                Contact.email.ilike(like_pattern),
            )
        )

    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    total = query.count()
    contacts = query.order_by(Contact.id.asc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return jsonify({
        'contacts': [contact_to_dict(c) for c in contacts],
        'total': total,
        'page': page,
        'per_page': per_page,
    })


@api_bp.route('/contacts', methods=['POST'])
def create_contact():
    """Create a single contact from JSON body."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    if not data.get('name'):
        return jsonify({'error': 'name is required'}), 400
    if not data.get('email'):
        return jsonify({'error': 'email is required'}), 400
    if not data.get('campaign_id'):
        return jsonify({'error': 'campaign_id is required'}), 400

    # Verify campaign exists
    campaign = db.session.get(Campaign, data['campaign_id'])
    if not campaign:
        return jsonify({'error': 'Campaign not found'}), 404

    contact = Contact(
        campaign_id=data['campaign_id'],
        name=data['name'],
        email=data['email'],
        company=data.get('company', ''),
        title=data.get('title', ''),
        external_id=data.get('external_id'),
        email_confidence=data.get('email_confidence'),
        response_likelihood=data.get('response_likelihood'),
        wave=data.get('wave'),
        ask_type=data.get('ask_type'),
        status=data.get('status', 'pending'),
        personalization_hooks=data.get('personalization_hooks'),
        notes=data.get('notes'),
        linkedin_url=data.get('linkedin_url'),
        needs_linkedin_verification=data.get('needs_linkedin_verification', False),
    )
    db.session.add(contact)
    db.session.commit()
    return jsonify(contact_to_dict(contact)), 201


@api_bp.route('/contacts/<int:contact_id>', methods=['GET'])
def get_contact(contact_id):
    """Get contact detail with nested emails and replies."""
    contact = db.session.get(Contact, contact_id)
    if not contact:
        return jsonify({'error': 'Contact not found'}), 404
    return jsonify(contact_to_dict(contact, include_emails=True, include_replies=True))


@api_bp.route('/contacts/<int:contact_id>', methods=['PUT'])
def update_contact(contact_id):
    """Update a contact."""
    contact = db.session.get(Contact, contact_id)
    if not contact:
        return jsonify({'error': 'Contact not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    updatable = [
        'name', 'email', 'company', 'title', 'external_id',
        'email_confidence', 'response_likelihood', 'wave', 'ask_type',
        'status', 'personalization_hooks', 'notes', 'linkedin_url',
        'needs_linkedin_verification',
    ]
    for field in updatable:
        if field in data:
            setattr(contact, field, data[field])

    db.session.commit()
    return jsonify(contact_to_dict(contact))


@api_bp.route('/contacts/<int:contact_id>', methods=['DELETE'])
def delete_contact(contact_id):
    """Delete a contact and all associated emails, replies, and metrics."""
    contact = db.session.get(Contact, contact_id)
    if not contact:
        return jsonify({'error': 'Contact not found'}), 404

    # Delete associated records
    Reply.query.filter_by(contact_id=contact.id).delete()
    Email.query.filter_by(contact_id=contact.id).delete()
    Metric.query.filter_by(contact_id=contact.id).delete()
    db.session.delete(contact)
    db.session.commit()
    return jsonify({'status': 'deleted', 'id': contact_id})


@api_bp.route('/contacts/<int:contact_id>/notes', methods=['PUT'])
def update_notes(contact_id):
    """Update notes for a contact."""
    contact = db.session.get(Contact, contact_id)
    if not contact:
        return jsonify({'error': 'Contact not found'}), 404

    data = request.get_json()
    if data is None:
        return jsonify({'error': 'No data provided'}), 400

    contact.notes = data.get('notes', '')
    db.session.commit()
    return jsonify(contact_to_dict(contact))


@api_bp.route('/contacts/<int:contact_id>/opt-out', methods=['POST'])
def opt_out_contact(contact_id):
    """Mark contact as opted_out and cancel all pending/scheduled emails."""
    contact = db.session.get(Contact, contact_id)
    if not contact:
        return jsonify({'error': 'Contact not found'}), 404

    contact.status = 'opted_out'

    # Cancel all pending/scheduled/draft emails
    cancelled = Email.query.filter(
        Email.contact_id == contact.id,
        Email.status.in_(['draft', 'scheduled', 'queued']),
    ).update({'status': 'cancelled'}, synchronize_session='fetch')

    db.session.commit()
    return jsonify({
        'status': 'opted_out',
        'emails_cancelled': cancelled,
        'contact': contact_to_dict(contact),
    })


@api_bp.route('/contacts/import', methods=['POST'])
def import_contacts():
    """Import contacts from a markdown campaign file."""
    data = request.get_json()
    if not data or not data.get('filepath'):
        return jsonify({'error': 'filepath is required'}), 400

    filepath = data['filepath']
    campaign_id = data.get('campaign_id')

    try:
        from importer.markdown_parser import parse_campaign_markdown, enrich_contacts
        from importer.contact_importer import import_contacts as do_import

        parsed = parse_campaign_markdown(filepath)
        enriched = enrich_contacts(parsed)
        contacts_created, emails_created, skipped = do_import(
            enriched, campaign_id=campaign_id
        )

        return jsonify({
            'contacts_created': contacts_created,
            'emails_created': emails_created,
            'skipped': skipped,
        }), 201
    except FileNotFoundError:
        return jsonify({'error': f'File not found: {filepath}'}), 400
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Import failed: {str(e)}'}), 500


@api_bp.route('/contacts/import-json', methods=['POST'])
def import_json():
    """Import contacts from a structured JSON payload (or file upload).

    Accepts either:
    - JSON body with {campaign: {...}, contacts: [...]}
    - File upload with key 'file' containing the same JSON

    Creates a Campaign (if needed), Contact records, and Email records.
    Idempotent via external_id: existing contacts are skipped.
    """
    # Handle file upload
    if request.files and 'file' in request.files:
        try:
            file_data = request.files['file'].read().decode('utf-8')
            data = __import__('json').loads(file_data)
        except Exception as e:
            return jsonify({'error': f'Invalid JSON file: {str(e)}'}), 400
    else:
        data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    contacts_list = data.get('contacts', [])
    if not contacts_list:
        return jsonify({'error': 'No contacts in payload'}), 400

    campaign_data = data.get('campaign', {})
    campaign_id = data.get('campaign_id')

    try:
        # Get or create campaign
        if campaign_id:
            campaign = db.session.get(Campaign, campaign_id)
            if not campaign:
                return jsonify({'error': f'Campaign {campaign_id} not found'}), 404
        else:
            campaign = Campaign(
                name=campaign_data.get('name', 'Imported Campaign'),
                description=campaign_data.get('description', ''),
                status='draft',
                send_start_hour=campaign_data.get('send_start_hour', 8),
                send_end_hour=campaign_data.get('send_end_hour', 17),
                min_interval_minutes=campaign_data.get('min_interval_minutes', 15),
                max_emails_per_day=campaign_data.get('max_emails_per_day', 10),
                followup1_delay_days=campaign_data.get('followup1_delay_days', 3),
                followup2_delay_days=campaign_data.get('followup2_delay_days', 7),
                timezone=campaign_data.get('timezone', 'America/Los_Angeles'),
            )
            db.session.add(campaign)
            db.session.flush()

        # Check existing external_ids for idempotency
        existing_ext_ids = set()
        existing_contacts = Contact.query.filter_by(
            campaign_id=campaign.id
        ).all()
        for c in existing_contacts:
            if c.external_id:
                existing_ext_ids.add(str(c.external_id))

        num_contacts = 0
        num_emails = 0
        num_skipped = 0

        for item in contacts_list:
            ext_id = str(item.get('external_id', ''))

            # Skip if already imported
            if ext_id and ext_id in existing_ext_ids:
                num_skipped += 1
                continue

            name = item.get('name', '')
            if not name:
                name = f"Contact at {item.get('company', 'Unknown')}"

            email_confidence = item.get('email_confidence', '')
            if email_confidence not in ('HIGH', 'MEDIUM', 'LOW', ''):
                email_confidence = ''

            contact = Contact(
                campaign_id=campaign.id,
                external_id=ext_id or None,
                company=item.get('company', ''),
                name=name,
                title=item.get('title', ''),
                email=item.get('email', ''),
                email_confidence=email_confidence or None,
                response_likelihood=item.get('response_likelihood') or None,
                wave=item.get('wave'),
                ask_type=item.get('ask_type') or None,
                status='pending',
                personalization_hooks=item.get('personalization_hooks') or None,
                needs_linkedin_verification=item.get('needs_linkedin', False),
                notes=item.get('status_raw', ''),
            )
            db.session.add(contact)
            db.session.flush()
            num_contacts += 1

            # Create email records
            for email_data in item.get('emails', []):
                email_record = Email(
                    contact_id=contact.id,
                    email_type=email_data.get('email_type', 'initial'),
                    subject=email_data.get('subject', '(no subject)'),
                    body=email_data.get('body', '(no content)'),
                    status='draft',
                )
                db.session.add(email_record)
                num_emails += 1

        db.session.commit()

        return jsonify({
            'campaign_id': campaign.id,
            'contacts_created': num_contacts,
            'emails_created': num_emails,
            'skipped': num_skipped,
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Import failed: {str(e)}'}), 500


@api_bp.route('/contacts/bulk', methods=['POST'])
def bulk_create_contacts():
    """Bulk create contacts from a JSON array."""
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({'error': 'Expected a JSON array of contacts'}), 400

    created = []
    errors = []
    for i, item in enumerate(data):
        if not item.get('name') or not item.get('email') or not item.get('campaign_id'):
            errors.append({
                'index': i,
                'error': 'name, email, and campaign_id are required',
            })
            continue

        campaign = db.session.get(Campaign, item['campaign_id'])
        if not campaign:
            errors.append({
                'index': i,
                'error': f"Campaign {item['campaign_id']} not found",
            })
            continue

        contact = Contact(
            campaign_id=item['campaign_id'],
            name=item['name'],
            email=item['email'],
            company=item.get('company', ''),
            title=item.get('title', ''),
            external_id=item.get('external_id'),
            email_confidence=item.get('email_confidence'),
            response_likelihood=item.get('response_likelihood'),
            wave=item.get('wave'),
            ask_type=item.get('ask_type'),
            status=item.get('status', 'pending'),
            notes=item.get('notes'),
        )
        db.session.add(contact)
        db.session.flush()
        created.append(contact_to_dict(contact))

    db.session.commit()
    return jsonify({
        'created': created,
        'errors': errors,
        'total_created': len(created),
    }), 201


# ---------------------------------------------------------------------------
# Email endpoints
# ---------------------------------------------------------------------------

@api_bp.route('/emails', methods=['GET'])
def list_emails():
    """List emails with optional filters."""
    query = Email.query

    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)

    email_type = request.args.get('email_type')
    if email_type:
        query = query.filter_by(email_type=email_type)

    contact_id = request.args.get('contact_id', type=int)
    if contact_id is not None:
        query = query.filter_by(contact_id=contact_id)

    emails = query.order_by(Email.id.asc()).all()
    return jsonify([email_to_dict(e) for e in emails])


@api_bp.route('/emails/<int:email_id>', methods=['GET'])
def get_email(email_id):
    """Get a single email by ID."""
    email = db.session.get(Email, email_id)
    if not email:
        return jsonify({'error': 'Email not found'}), 404
    return jsonify(email_to_dict(email))


@api_bp.route('/emails/<int:email_id>', methods=['PUT'])
def edit_email(email_id):
    """Edit email subject/body. Only allowed for draft or scheduled emails."""
    email = db.session.get(Email, email_id)
    if not email:
        return jsonify({'error': 'Email not found'}), 404

    if email.status not in ('draft', 'scheduled'):
        return jsonify({
            'error': f'Cannot edit email with status {email.status}',
        }), 400

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    if 'subject' in data:
        email.subject = data['subject']
    if 'body' in data:
        email.body = data['body']

    db.session.commit()
    return jsonify(email_to_dict(email))


@api_bp.route('/emails/<int:email_id>/send-now', methods=['POST'])
def send_email_now(email_id):
    """Send an email immediately."""
    email = db.session.get(Email, email_id)
    if not email:
        return jsonify({'error': 'Email not found'}), 404

    if email.status == 'sent':
        return jsonify({'error': 'Email already sent'}), 400

    try:
        from gmail.sender import send_email
        msg_id, thread_id = send_email(email)
        return jsonify({
            'status': 'sent',
            'gmail_message_id': msg_id,
            'gmail_thread_id': thread_id,
        })
    except Exception as e:
        return jsonify({'error': f'Send failed: {str(e)}'}), 500


@api_bp.route('/emails/<int:email_id>/cancel', methods=['POST'])
def cancel_email(email_id):
    """Cancel a scheduled email."""
    email = db.session.get(Email, email_id)
    if not email:
        return jsonify({'error': 'Email not found'}), 404

    if email.status not in ('draft', 'scheduled', 'queued'):
        return jsonify({
            'error': f'Cannot cancel email with status {email.status}',
        }), 400

    email.status = 'cancelled'
    db.session.commit()
    return jsonify(email_to_dict(email))


@api_bp.route('/emails/queue', methods=['GET'])
def get_queue():
    """Get current send queue."""
    from scheduler.queue import get_queue_status
    campaign_id = request.args.get('campaign_id', type=int)
    queue = get_queue_status(campaign_id=campaign_id)
    return jsonify(queue)


@api_bp.route('/emails/all', methods=['GET'])
def list_all_emails():
    """List all emails for a campaign, grouped by status category.

    Query params:
        campaign_id (required): Campaign to list emails for
        category: 'planned' (draft), 'scheduled', 'sent', 'all' (default: 'all')
        wave: Filter by contact wave number
    """
    campaign_id = request.args.get('campaign_id', type=int)
    if not campaign_id:
        return jsonify({'error': 'campaign_id is required'}), 400

    category = request.args.get('category', 'all')
    wave = request.args.get('wave', type=int)

    query = (
        Email.query
        .join(Contact)
        .filter(Contact.campaign_id == campaign_id)
    )

    if wave is not None:
        query = query.filter(Contact.wave == wave)

    status_map = {
        'planned': ['draft'],
        'scheduled': ['scheduled', 'queued'],
        'sent': ['sent'],
        'failed': ['failed'],
        'cancelled': ['cancelled'],
    }
    if category != 'all' and category in status_map:
        query = query.filter(Email.status.in_(status_map[category]))

    emails = query.order_by(
        Contact.wave.asc(), Contact.external_id.asc(), Email.email_type.asc()
    ).all()

    result = []
    for e in emails:
        c = e.contact
        result.append({
            'id': e.id,
            'contact_id': c.id,
            'contact_name': c.name,
            'contact_email': c.email,
            'company': c.company,
            'wave': c.wave,
            'email_type': e.email_type,
            'subject': e.subject,
            'body': e.body,
            'status': e.status,
            'scheduled_at': e.scheduled_at.isoformat() if e.scheduled_at else None,
            'sent_at': e.sent_at.isoformat() if e.sent_at else None,
            'email_confidence': c.email_confidence,
        })

    # Summary counts
    all_emails = (
        Email.query.join(Contact).filter(Contact.campaign_id == campaign_id)
    )
    if wave is not None:
        all_emails = all_emails.filter(Contact.wave == wave)

    counts = {}
    for row in (
        all_emails.with_entities(Email.status, db.func.count(Email.id))
        .group_by(Email.status).all()
    ):
        counts[row[0]] = row[1]

    # Get distinct waves for filter
    waves = [
        w[0] for w in
        db.session.query(Contact.wave)
        .filter(Contact.campaign_id == campaign_id, Contact.wave.isnot(None))
        .distinct()
        .order_by(Contact.wave.asc())
        .all()
    ]

    return jsonify({
        'emails': result,
        'counts': {
            'planned': counts.get('draft', 0),
            'scheduled': counts.get('scheduled', 0) + counts.get('queued', 0),
            'sent': counts.get('sent', 0),
            'failed': counts.get('failed', 0),
            'cancelled': counts.get('cancelled', 0),
        },
        'waves': waves,
        'total': len(result),
    })


@api_bp.route('/emails/generate-queue', methods=['POST'])
def generate_queue():
    """Generate daily queue for a campaign."""
    data = request.get_json()
    if not data or not data.get('campaign_id'):
        return jsonify({'error': 'campaign_id is required'}), 400

    from scheduler.queue import generate_daily_queue
    count = generate_daily_queue(data['campaign_id'])
    return jsonify({'scheduled': count})


@api_bp.route('/emails/schedule-preview', methods=['GET'])
def schedule_preview():
    """Preview the next N days of email sends for a campaign.

    Query params:
        campaign_id (required): Campaign to preview
        days: Number of days to look ahead (default: 7, max: 30)
    """
    campaign_id = request.args.get('campaign_id', type=int)
    if not campaign_id:
        return jsonify({'error': 'campaign_id is required'}), 400

    days = request.args.get('days', 7, type=int)
    days = min(days, 30)

    from scheduler.queue import simulate_schedule
    schedule = simulate_schedule(campaign_id, days=days)

    # Summary
    total_initials = sum(
        1 for day in schedule for e in day['emails'] if e['email_type'] == 'initial'
    )
    total_fu1 = sum(
        1 for day in schedule for e in day['emails'] if e['email_type'] == 'followup1'
    )
    total_fu2 = sum(
        1 for day in schedule for e in day['emails'] if e['email_type'] == 'followup2'
    )

    return jsonify({
        'campaign_id': campaign_id,
        'days': days,
        'schedule': schedule,
        'summary': {
            'total_emails': total_initials + total_fu1 + total_fu2,
            'initial': total_initials,
            'followup1': total_fu1,
            'followup2': total_fu2,
        },
    })


# ---------------------------------------------------------------------------
# Reply endpoints
# ---------------------------------------------------------------------------

@api_bp.route('/replies', methods=['GET'])
def list_replies():
    """List all replies."""
    replies = Reply.query.order_by(Reply.received_at.desc()).all()
    return jsonify([reply_to_dict(r) for r in replies])


@api_bp.route('/replies/contact/<int:contact_id>', methods=['GET'])
def replies_for_contact(contact_id):
    """Get replies for a specific contact."""
    contact = db.session.get(Contact, contact_id)
    if not contact:
        return jsonify({'error': 'Contact not found'}), 404

    replies = Reply.query.filter_by(contact_id=contact_id).order_by(
        Reply.received_at.desc()
    ).all()
    return jsonify([reply_to_dict(r) for r in replies])


@api_bp.route('/replies/check-now', methods=['POST'])
def check_replies_now():
    """Trigger immediate reply check."""
    try:
        from gmail.reader import check_for_replies
        new_replies = check_for_replies()
        return jsonify({
            'new_replies': len(new_replies),
            'details': [
                {'contact_id': cid, 'snippet': snippet}
                for cid, snippet in new_replies
            ],
        })
    except Exception as e:
        return jsonify({'error': f'Reply check failed: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# Metrics / Dashboard endpoints
# ---------------------------------------------------------------------------

@api_bp.route('/metrics/dashboard', methods=['GET'])
def dashboard_metrics():
    """Dashboard data: total sent, response rate, avg response time, etc."""
    total_contacts = Contact.query.count()
    total_sent = Email.query.filter_by(status='sent').count()
    total_replied = Reply.query.count()
    total_bounced = Metric.query.filter_by(metric_type='bounced').count()

    response_rate = (total_replied / total_sent * 100) if total_sent > 0 else 0.0

    # Average response time (hours) for contacts that replied
    avg_response_time = _compute_avg_response_time()

    # Emails by status
    emails_by_status = {}
    for status_row in db.session.query(
        Email.status, db.func.count(Email.id)
    ).group_by(Email.status).all():
        emails_by_status[status_row[0]] = status_row[1]

    # Contacts by status
    contacts_by_status = {}
    for status_row in db.session.query(
        Contact.status, db.func.count(Contact.id)
    ).group_by(Contact.status).all():
        contacts_by_status[status_row[0]] = status_row[1]

    # Sent by day
    sent_by_day = []
    sent_rows = db.session.query(
        db.func.date(Email.sent_at), db.func.count(Email.id)
    ).filter(
        Email.status == 'sent', Email.sent_at.isnot(None)
    ).group_by(db.func.date(Email.sent_at)).order_by(
        db.func.date(Email.sent_at)
    ).all()
    for date_val, count in sent_rows:
        sent_by_day.append({'date': str(date_val), 'count': count})

    # Replies by day
    replies_by_day = []
    reply_rows = db.session.query(
        db.func.date(Reply.received_at), db.func.count(Reply.id)
    ).group_by(db.func.date(Reply.received_at)).order_by(
        db.func.date(Reply.received_at)
    ).all()
    for date_val, count in reply_rows:
        replies_by_day.append({'date': str(date_val), 'count': count})

    return jsonify({
        'total_contacts': total_contacts,
        'total_sent': total_sent,
        'total_replied': total_replied,
        'total_bounced': total_bounced,
        'response_rate': round(response_rate, 1),
        'avg_response_time_hours': avg_response_time,
        'emails_by_status': emails_by_status,
        'contacts_by_status': contacts_by_status,
        'sent_by_day': sent_by_day,
        'replies_by_day': replies_by_day,
    })


@api_bp.route('/metrics/contacts/<int:contact_id>', methods=['GET'])
def contact_metrics(contact_id):
    """Per-contact metrics timeline."""
    contact = db.session.get(Contact, contact_id)
    if not contact:
        return jsonify({'error': 'Contact not found'}), 404

    metrics = Metric.query.filter_by(contact_id=contact_id).order_by(
        Metric.recorded_at.asc()
    ).all()

    return jsonify({
        'contact_id': contact_id,
        'metrics': [
            {
                'id': m.id,
                'metric_type': m.metric_type,
                'value': m.value,
                'recorded_at': m.recorded_at.isoformat() if m.recorded_at else None,
            }
            for m in metrics
        ],
    })


def _compute_avg_response_time():
    """Compute average response time in hours across all replied contacts.

    For each reply, find the most recent sent email to that contact before
    the reply was received, and compute the delta.
    """
    replies = Reply.query.all()
    if not replies:
        return 0.0

    total_hours = 0.0
    count = 0

    for reply in replies:
        # Find the most recent sent email for this contact before the reply
        last_sent = Email.query.filter(
            Email.contact_id == reply.contact_id,
            Email.status == 'sent',
            Email.sent_at.isnot(None),
        ).order_by(Email.sent_at.desc()).first()

        if last_sent and last_sent.sent_at and reply.received_at:
            delta = reply.received_at - last_sent.sent_at
            total_hours += delta.total_seconds() / 3600
            count += 1

    return round(total_hours / count, 1) if count > 0 else 0.0


# ---------------------------------------------------------------------------
# Test email endpoint
# ---------------------------------------------------------------------------

@api_bp.route('/test-email', methods=['POST'])
def send_test_email_endpoint():
    """Send a test email to verify Gmail connection works."""
    data = request.get_json()
    if not data or not data.get('to'):
        return jsonify({'error': 'to (email address) is required'}), 400

    to_email = data['to']

    try:
        from gmail.sender import send_test_email
        message_id = send_test_email(to_email)
        return jsonify({'status': 'sent', 'to': to_email, 'message_id': message_id})
    except Exception as e:
        return jsonify({'error': f'Failed to send test email: {str(e)}'}), 500

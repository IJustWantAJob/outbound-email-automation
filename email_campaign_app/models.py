"""SQLAlchemy models for the Gmail Email Campaign Manager."""

from datetime import datetime, timezone

from database import db


class Campaign(db.Model):
    """A campaign groups contacts and manages sending configuration."""

    __tablename__ = 'campaigns'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default='draft',
    )
    send_start_hour = db.Column(db.Integer, nullable=False, default=8)
    send_end_hour = db.Column(db.Integer, nullable=False, default=17)
    min_interval_minutes = db.Column(db.Integer, nullable=False, default=15)
    max_emails_per_day = db.Column(db.Integer, nullable=False, default=23)
    followup1_delay_days = db.Column(db.Integer, nullable=False, default=3)
    followup2_delay_days = db.Column(db.Integer, nullable=False, default=7)
    timezone = db.Column(
        db.String(50), nullable=False, default='America/Los_Angeles'
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    contacts = db.relationship('Contact', backref='campaign', lazy=True)
    reports = db.relationship('Report', backref='campaign', lazy=True)

    def __repr__(self):
        return f'<Campaign {self.id}: {self.name} [{self.status}]>'


class Contact(db.Model):
    """A contact within a campaign to receive emails."""

    __tablename__ = 'contacts'
    __table_args__ = (
        db.Index('ix_contacts_campaign_id', 'campaign_id'),
        db.Index('ix_contacts_status', 'status'),
        db.Index('ix_contacts_email', 'email'),
    )

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(
        db.Integer, db.ForeignKey('campaigns.id'), nullable=False
    )
    external_id = db.Column(db.String(100), nullable=True)
    company = db.Column(db.String(200), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    title = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(254), nullable=False)
    email_confidence = db.Column(
        db.String(10), nullable=True
    )  # HIGH, MEDIUM, LOW
    response_likelihood = db.Column(db.Integer, nullable=True)  # 1-5
    wave = db.Column(db.Integer, nullable=True)
    ask_type = db.Column(db.String(100), nullable=True)
    status = db.Column(
        db.String(30),
        nullable=False,
        default='pending',
    )
    personalization_hooks = db.Column(db.Text, nullable=True)  # JSON string
    notes = db.Column(db.Text, nullable=True)
    linkedin_url = db.Column(db.String(500), nullable=True)
    needs_linkedin_verification = db.Column(
        db.Boolean, nullable=False, default=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    emails = db.relationship('Email', backref='contact', lazy=True)
    replies = db.relationship('Reply', backref='contact', lazy=True)
    metrics = db.relationship('Metric', backref='contact', lazy=True)

    def __repr__(self):
        return f'<Contact {self.id}: {self.name} <{self.email}> [{self.status}]>'


class Email(db.Model):
    """An individual email sent (or to be sent) to a contact."""

    __tablename__ = 'emails'
    __table_args__ = (
        db.Index('ix_emails_contact_id', 'contact_id'),
        db.Index('ix_emails_status', 'status'),
        db.Index('ix_emails_scheduled_at', 'scheduled_at'),
        db.Index('ix_emails_gmail_thread_id', 'gmail_thread_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(
        db.Integer, db.ForeignKey('contacts.id'), nullable=False
    )
    email_type = db.Column(
        db.String(20), nullable=False
    )  # initial, followup1, followup2, manual
    subject = db.Column(db.String(500), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default='draft',
    )
    scheduled_at = db.Column(db.DateTime, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    gmail_message_id = db.Column(db.String(200), nullable=True)
    gmail_thread_id = db.Column(db.String(200), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return (
            f'<Email {self.id}: {self.email_type} to contact '
            f'{self.contact_id} [{self.status}]>'
        )


class Reply(db.Model):
    """A reply received from a contact via Gmail."""

    __tablename__ = 'replies'
    __table_args__ = (
        db.Index('ix_replies_contact_id', 'contact_id'),
        db.Index('ix_replies_gmail_thread_id', 'gmail_thread_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(
        db.Integer, db.ForeignKey('contacts.id'), nullable=False
    )
    email_id = db.Column(
        db.Integer, db.ForeignKey('emails.id'), nullable=True
    )
    gmail_message_id = db.Column(db.String(200), nullable=True)
    gmail_thread_id = db.Column(db.String(200), nullable=True)
    from_email = db.Column(db.String(254), nullable=False)
    subject = db.Column(db.String(500), nullable=True)
    snippet = db.Column(db.Text, nullable=True)
    received_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    detected_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationship to the email this replies to
    email = db.relationship('Email', backref='replies', lazy=True)

    def __repr__(self):
        return (
            f'<Reply {self.id}: from {self.from_email} '
            f'to contact {self.contact_id}>'
        )


class Metric(db.Model):
    """A tracking metric (sent, opened, replied, bounced) for a contact."""

    __tablename__ = 'metrics'

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(
        db.Integer, db.ForeignKey('contacts.id'), nullable=False
    )
    metric_type = db.Column(
        db.String(20), nullable=False
    )  # sent, opened, replied, bounced
    value = db.Column(db.Text, nullable=True)
    recorded_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return (
            f'<Metric {self.id}: {self.metric_type} '
            f'for contact {self.contact_id}>'
        )


class GmailToken(db.Model):
    """Encrypted OAuth token storage for Gmail accounts."""

    __tablename__ = 'gmail_tokens'

    id = db.Column(db.Integer, primary_key=True)
    email_address = db.Column(
        db.String(254), unique=True, nullable=False
    )
    token_json = db.Column(db.Text, nullable=False)  # Fernet encrypted
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return (
            f'<GmailToken {self.id}: {self.email_address} '
            f'[{"active" if self.is_active else "inactive"}]>'
        )


class ApiKey(db.Model):
    """Encrypted API key storage (Anthropic, etc.)."""

    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), unique=True, nullable=False)  # 'anthropic'
    encrypted_key = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f'<ApiKey {self.id}: {self.provider} [{"active" if self.is_active else "inactive"}]>'


class SenderProfile(db.Model):
    """Singleton sender profile — company info, sender identity, and target audience.

    Populated via the onboarding form on first launch. Used by the nightly
    automation scripts to generate prompts and personalize outreach.
    """

    __tablename__ = 'sender_profiles'

    id = db.Column(db.Integer, primary_key=True)

    # Company info
    company_name = db.Column(db.String(200), nullable=False)
    company_description = db.Column(db.Text, nullable=True)
    industry = db.Column(db.String(100), nullable=True)
    product_description = db.Column(db.Text, nullable=True)

    # Sender identity
    sender_name = db.Column(db.String(200), nullable=False)
    sender_title = db.Column(db.String(200), nullable=True)
    sender_email = db.Column(db.String(254), nullable=True)
    sender_background = db.Column(db.Text, nullable=True)
    linkedin_url = db.Column(db.String(500), nullable=True)
    university = db.Column(db.String(200), nullable=True)
    accelerator = db.Column(db.String(200), nullable=True)

    # Target audience
    target_customer_description = db.Column(db.Text, nullable=True)
    target_segments = db.Column(db.JSON, nullable=True)  # [{name, description, priority}]
    geography = db.Column(db.String(200), nullable=True)

    # Messaging style
    tone_voice = db.Column(
        db.String(200), nullable=True,
        default='Curious, respectful, not salesy'
    )
    key_metrics = db.Column(db.Text, nullable=True)
    pricing_notes = db.Column(db.Text, nullable=True)  # INTERNAL ONLY — never in emails

    # Timestamps
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f'<SenderProfile {self.id}: {self.company_name}>'


class Report(db.Model):
    """Generated campaign reports."""

    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(
        db.Integer, db.ForeignKey('campaigns.id'), nullable=False
    )
    report_type = db.Column(
        db.String(30), nullable=False
    )  # daily_summary, weekly_summary, campaign_final
    filename = db.Column(db.String(300), nullable=True)
    content = db.Column(db.Text, nullable=True)
    generated_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return (
            f'<Report {self.id}: {self.report_type} '
            f'for campaign {self.campaign_id}>'
        )

"""Comprehensive tests for all database models and the health check endpoint."""

import json
from datetime import datetime, timezone

import pytest

from models import Campaign, Contact, Email, Reply, Metric, GmailToken, Report
from database import db as _db


# ---------------------------------------------------------------------------
# Campaign Tests
# ---------------------------------------------------------------------------

class TestCampaign:

    def test_create_campaign(self, db):
        """Create a campaign and verify it persists."""
        campaign = Campaign(name='Test Campaign', description='A test')
        db.session.add(campaign)
        db.session.commit()

        saved = Campaign.query.first()
        assert saved is not None
        assert saved.name == 'Test Campaign'
        assert saved.description == 'A test'
        assert saved.id is not None

    def test_campaign_default_values(self, db):
        """Verify all default column values on a new campaign."""
        campaign = Campaign(name='Defaults Test')
        db.session.add(campaign)
        db.session.commit()

        saved = Campaign.query.first()
        assert saved.status == 'draft'
        assert saved.send_start_hour == 8
        assert saved.send_end_hour == 17
        assert saved.min_interval_minutes == 15
        assert saved.max_emails_per_day == 10
        assert saved.followup1_delay_days == 3
        assert saved.followup2_delay_days == 7
        assert saved.timezone == 'America/Los_Angeles'
        assert saved.created_at is not None
        assert saved.updated_at is not None

    def test_campaign_update(self, db):
        """Update a campaign's fields and verify persistence."""
        campaign = Campaign(name='Original Name')
        db.session.add(campaign)
        db.session.commit()

        campaign.name = 'Updated Name'
        campaign.status = 'active'
        campaign.max_emails_per_day = 20
        db.session.commit()

        saved = Campaign.query.first()
        assert saved.name == 'Updated Name'
        assert saved.status == 'active'
        assert saved.max_emails_per_day == 20

    def test_campaign_status_values(self, db):
        """Campaign status field accepts all valid string values."""
        for status in ('draft', 'active', 'paused', 'completed'):
            campaign = Campaign(name=f'Campaign {status}', status=status)
            db.session.add(campaign)
        db.session.commit()

        campaigns = Campaign.query.all()
        statuses = {c.status for c in campaigns}
        assert statuses == {'draft', 'active', 'paused', 'completed'}

    def test_campaign_repr(self, db):
        """Campaign repr includes id, name, and status."""
        campaign = Campaign(name='Repr Test', status='active')
        db.session.add(campaign)
        db.session.commit()

        r = repr(campaign)
        assert 'Repr Test' in r
        assert 'active' in r


# ---------------------------------------------------------------------------
# Contact Tests
# ---------------------------------------------------------------------------

class TestContact:

    def _make_campaign(self, db):
        campaign = Campaign(name='Contact Campaign')
        db.session.add(campaign)
        db.session.commit()
        return campaign

    def test_create_contact(self, db):
        """Create a contact linked to a campaign."""
        campaign = self._make_campaign(db)
        contact = Contact(
            campaign_id=campaign.id,
            name='John Doe',
            email='john@example.com',
            company='Acme Inc',
            title='CTO',
            email_confidence='HIGH',
            response_likelihood=4,
            wave=1,
            ask_type='demo',
            linkedin_url='https://linkedin.com/in/johndoe',
        )
        db.session.add(contact)
        db.session.commit()

        saved = Contact.query.first()
        assert saved.name == 'John Doe'
        assert saved.email == 'john@example.com'
        assert saved.company == 'Acme Inc'
        assert saved.title == 'CTO'
        assert saved.email_confidence == 'HIGH'
        assert saved.response_likelihood == 4
        assert saved.wave == 1
        assert saved.ask_type == 'demo'
        assert saved.linkedin_url == 'https://linkedin.com/in/johndoe'
        assert saved.campaign_id == campaign.id

    def test_contact_default_values(self, db):
        """Verify default status and needs_linkedin_verification."""
        campaign = self._make_campaign(db)
        contact = Contact(
            campaign_id=campaign.id,
            name='Jane Doe',
            email='jane@example.com',
        )
        db.session.add(contact)
        db.session.commit()

        saved = Contact.query.first()
        assert saved.status == 'pending'
        assert saved.needs_linkedin_verification is False
        assert saved.created_at is not None

    def test_contact_status_transitions(self, db):
        """Contact status field accepts all valid values."""
        campaign = self._make_campaign(db)
        valid_statuses = [
            'pending', 'scheduled', 'initial_sent', 'followup1_sent',
            'followup2_sent', 'replied', 'bounced', 'opted_out',
        ]
        for i, status in enumerate(valid_statuses):
            contact = Contact(
                campaign_id=campaign.id,
                name=f'Contact {i}',
                email=f'contact{i}@example.com',
                status=status,
            )
            db.session.add(contact)
        db.session.commit()

        contacts = Contact.query.all()
        statuses = {c.status for c in contacts}
        assert statuses == set(valid_statuses)

    def test_contact_personalization_hooks_json(self, db):
        """personalization_hooks stores a JSON string correctly."""
        campaign = self._make_campaign(db)
        hooks = json.dumps({'pain_point': 'high energy costs', 'recent_news': 'expansion'})
        contact = Contact(
            campaign_id=campaign.id,
            name='Hook Test',
            email='hook@example.com',
            personalization_hooks=hooks,
        )
        db.session.add(contact)
        db.session.commit()

        saved = Contact.query.first()
        parsed = json.loads(saved.personalization_hooks)
        assert parsed['pain_point'] == 'high energy costs'


# ---------------------------------------------------------------------------
# Email Tests
# ---------------------------------------------------------------------------

class TestEmail:

    def _make_contact(self, db):
        campaign = Campaign(name='Email Campaign')
        db.session.add(campaign)
        db.session.commit()
        contact = Contact(
            campaign_id=campaign.id,
            name='Email Recipient',
            email='recipient@example.com',
        )
        db.session.add(contact)
        db.session.commit()
        return contact

    def test_create_email(self, db):
        """Create an email linked to a contact."""
        contact = self._make_contact(db)
        email = Email(
            contact_id=contact.id,
            email_type='initial',
            subject='Hello from Campaign',
            body='We noticed your company...',
        )
        db.session.add(email)
        db.session.commit()

        saved = Email.query.first()
        assert saved.contact_id == contact.id
        assert saved.email_type == 'initial'
        assert saved.subject == 'Hello from Campaign'
        assert saved.body == 'We noticed your company...'
        assert saved.status == 'draft'

    def test_email_types(self, db):
        """All four email types can be created."""
        contact = self._make_contact(db)
        for email_type in ('initial', 'followup1', 'followup2', 'manual'):
            email = Email(
                contact_id=contact.id,
                email_type=email_type,
                subject=f'Subject {email_type}',
                body=f'Body {email_type}',
            )
            db.session.add(email)
        db.session.commit()

        emails = Email.query.all()
        types = {e.email_type for e in emails}
        assert types == {'initial', 'followup1', 'followup2', 'manual'}

    def test_email_status_values(self, db):
        """Email status field accepts all valid values."""
        contact = self._make_contact(db)
        valid_statuses = ['draft', 'queued', 'scheduled', 'sent', 'failed', 'cancelled']
        for i, status in enumerate(valid_statuses):
            email = Email(
                contact_id=contact.id,
                email_type='initial',
                subject=f'Subject {i}',
                body=f'Body {i}',
                status=status,
            )
            db.session.add(email)
        db.session.commit()

        emails = Email.query.all()
        statuses = {e.status for e in emails}
        assert statuses == set(valid_statuses)

    def test_email_gmail_fields(self, db):
        """Gmail message/thread IDs and scheduled_at persist."""
        contact = self._make_contact(db)
        now = datetime.now(timezone.utc)
        email = Email(
            contact_id=contact.id,
            email_type='initial',
            subject='Test',
            body='Body',
            status='sent',
            scheduled_at=now,
            sent_at=now,
            gmail_message_id='msg_123',
            gmail_thread_id='thread_456',
        )
        db.session.add(email)
        db.session.commit()

        saved = Email.query.first()
        assert saved.gmail_message_id == 'msg_123'
        assert saved.gmail_thread_id == 'thread_456'
        assert saved.scheduled_at is not None
        assert saved.sent_at is not None


# ---------------------------------------------------------------------------
# Reply Tests
# ---------------------------------------------------------------------------

class TestReply:

    def test_create_reply(self, db):
        """Create a reply linked to a contact and email."""
        campaign = Campaign(name='Reply Campaign')
        db.session.add(campaign)
        db.session.commit()

        contact = Contact(
            campaign_id=campaign.id,
            name='Replier',
            email='replier@example.com',
        )
        db.session.add(contact)
        db.session.commit()

        email = Email(
            contact_id=contact.id,
            email_type='initial',
            subject='Original',
            body='Hello',
            status='sent',
        )
        db.session.add(email)
        db.session.commit()

        reply = Reply(
            contact_id=contact.id,
            email_id=email.id,
            gmail_message_id='reply_msg_001',
            gmail_thread_id='thread_001',
            from_email='replier@example.com',
            subject='Re: Original',
            snippet='Thanks for reaching out...',
        )
        db.session.add(reply)
        db.session.commit()

        saved = Reply.query.first()
        assert saved.contact_id == contact.id
        assert saved.email_id == email.id
        assert saved.gmail_message_id == 'reply_msg_001'
        assert saved.gmail_thread_id == 'thread_001'
        assert saved.from_email == 'replier@example.com'
        assert saved.subject == 'Re: Original'
        assert saved.snippet == 'Thanks for reaching out...'
        assert saved.received_at is not None
        assert saved.detected_at is not None

    def test_reply_without_email_id(self, db):
        """Reply can be created with nullable email_id."""
        campaign = Campaign(name='Reply Campaign 2')
        db.session.add(campaign)
        db.session.commit()

        contact = Contact(
            campaign_id=campaign.id,
            name='Orphan Replier',
            email='orphan@example.com',
        )
        db.session.add(contact)
        db.session.commit()

        reply = Reply(
            contact_id=contact.id,
            email_id=None,
            from_email='orphan@example.com',
        )
        db.session.add(reply)
        db.session.commit()

        saved = Reply.query.first()
        assert saved.email_id is None


# ---------------------------------------------------------------------------
# Metric Tests
# ---------------------------------------------------------------------------

class TestMetric:

    def test_create_metric(self, db):
        """Create a metric linked to a contact."""
        campaign = Campaign(name='Metric Campaign')
        db.session.add(campaign)
        db.session.commit()

        contact = Contact(
            campaign_id=campaign.id,
            name='Metric Contact',
            email='metric@example.com',
        )
        db.session.add(contact)
        db.session.commit()

        metric = Metric(
            contact_id=contact.id,
            metric_type='sent',
            value='1',
        )
        db.session.add(metric)
        db.session.commit()

        saved = Metric.query.first()
        assert saved.contact_id == contact.id
        assert saved.metric_type == 'sent'
        assert saved.value == '1'
        assert saved.recorded_at is not None

    def test_metric_types(self, db):
        """All metric types can be created."""
        campaign = Campaign(name='Metric Types Campaign')
        db.session.add(campaign)
        db.session.commit()

        contact = Contact(
            campaign_id=campaign.id,
            name='Metric Types Contact',
            email='mt@example.com',
        )
        db.session.add(contact)
        db.session.commit()

        for mt in ('sent', 'opened', 'replied', 'bounced'):
            db.session.add(Metric(
                contact_id=contact.id,
                metric_type=mt,
                value='1',
            ))
        db.session.commit()

        metrics = Metric.query.all()
        types = {m.metric_type for m in metrics}
        assert types == {'sent', 'opened', 'replied', 'bounced'}


# ---------------------------------------------------------------------------
# GmailToken Tests
# ---------------------------------------------------------------------------

class TestGmailToken:

    def test_create_gmail_token(self, db):
        """Create a Gmail token record."""
        token = GmailToken(
            email_address='test@gmail.com',
            token_json='{"encrypted": "data"}',
        )
        db.session.add(token)
        db.session.commit()

        saved = GmailToken.query.first()
        assert saved.email_address == 'test@gmail.com'
        assert saved.token_json == '{"encrypted": "data"}'
        assert saved.is_active is True
        assert saved.created_at is not None

    def test_gmail_token_unique_email(self, db):
        """email_address must be unique."""
        token1 = GmailToken(
            email_address='unique@gmail.com',
            token_json='{"token": "1"}',
        )
        db.session.add(token1)
        db.session.commit()

        token2 = GmailToken(
            email_address='unique@gmail.com',
            token_json='{"token": "2"}',
        )
        db.session.add(token2)
        with pytest.raises(Exception):
            db.session.commit()


# ---------------------------------------------------------------------------
# Report Tests
# ---------------------------------------------------------------------------

class TestReport:

    def test_create_report(self, db):
        """Create a report linked to a campaign."""
        campaign = Campaign(name='Report Campaign')
        db.session.add(campaign)
        db.session.commit()

        report = Report(
            campaign_id=campaign.id,
            report_type='daily_summary',
            filename='report_2026_03_03.html',
            content='<h1>Daily Summary</h1>',
        )
        db.session.add(report)
        db.session.commit()

        saved = Report.query.first()
        assert saved.campaign_id == campaign.id
        assert saved.report_type == 'daily_summary'
        assert saved.filename == 'report_2026_03_03.html'
        assert saved.content == '<h1>Daily Summary</h1>'
        assert saved.generated_at is not None

    def test_report_types(self, db):
        """All report types can be created."""
        campaign = Campaign(name='Report Types Campaign')
        db.session.add(campaign)
        db.session.commit()

        for rt in ('daily_summary', 'weekly_summary', 'campaign_final'):
            db.session.add(Report(
                campaign_id=campaign.id,
                report_type=rt,
            ))
        db.session.commit()

        reports = Report.query.all()
        types = {r.report_type for r in reports}
        assert types == {'daily_summary', 'weekly_summary', 'campaign_final'}


# ---------------------------------------------------------------------------
# Relationship Tests
# ---------------------------------------------------------------------------

class TestRelationships:

    def test_campaign_contacts_relationship(self, db):
        """Campaign.contacts returns the linked contact list."""
        campaign = Campaign(name='Relationship Campaign')
        db.session.add(campaign)
        db.session.commit()

        for i in range(3):
            db.session.add(Contact(
                campaign_id=campaign.id,
                name=f'Contact {i}',
                email=f'c{i}@example.com',
            ))
        db.session.commit()

        assert len(campaign.contacts) == 3

    def test_contact_emails_relationship(self, db):
        """Contact.emails returns the linked email list."""
        campaign = Campaign(name='Email Rel Campaign')
        db.session.add(campaign)
        db.session.commit()

        contact = Contact(
            campaign_id=campaign.id,
            name='Email Rel Contact',
            email='erc@example.com',
        )
        db.session.add(contact)
        db.session.commit()

        for etype in ('initial', 'followup1', 'followup2'):
            db.session.add(Email(
                contact_id=contact.id,
                email_type=etype,
                subject=f'Subject {etype}',
                body=f'Body {etype}',
            ))
        db.session.commit()

        assert len(contact.emails) == 3

    def test_contact_replies_relationship(self, db):
        """Contact.replies returns the linked reply list."""
        campaign = Campaign(name='Reply Rel Campaign')
        db.session.add(campaign)
        db.session.commit()

        contact = Contact(
            campaign_id=campaign.id,
            name='Reply Rel Contact',
            email='rrc@example.com',
        )
        db.session.add(contact)
        db.session.commit()

        db.session.add(Reply(
            contact_id=contact.id,
            from_email='rrc@example.com',
        ))
        db.session.commit()

        assert len(contact.replies) == 1

    def test_contact_metrics_relationship(self, db):
        """Contact.metrics returns the linked metric list."""
        campaign = Campaign(name='Metric Rel Campaign')
        db.session.add(campaign)
        db.session.commit()

        contact = Contact(
            campaign_id=campaign.id,
            name='Metric Rel Contact',
            email='mrc@example.com',
        )
        db.session.add(contact)
        db.session.commit()

        for mt in ('sent', 'replied'):
            db.session.add(Metric(
                contact_id=contact.id,
                metric_type=mt,
            ))
        db.session.commit()

        assert len(contact.metrics) == 2

    def test_campaign_reports_relationship(self, db):
        """Campaign.reports returns the linked report list."""
        campaign = Campaign(name='Report Rel Campaign')
        db.session.add(campaign)
        db.session.commit()

        db.session.add(Report(
            campaign_id=campaign.id,
            report_type='daily_summary',
        ))
        db.session.add(Report(
            campaign_id=campaign.id,
            report_type='weekly_summary',
        ))
        db.session.commit()

        assert len(campaign.reports) == 2


# ---------------------------------------------------------------------------
# Health Check Endpoint Test
# ---------------------------------------------------------------------------

class TestHealthCheck:

    def test_health_check_returns_200(self, client):
        """GET /api/health returns 200 with {status: ok}."""
        response = client.get('/api/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'

    def test_security_headers_present(self, client):
        """Responses include security headers."""
        response = client.get('/api/health')
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'
        assert response.headers.get('X-Frame-Options') == 'DENY'
        assert response.headers.get('X-XSS-Protection') == '1; mode=block'
        assert response.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'

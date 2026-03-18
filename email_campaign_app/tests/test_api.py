"""Comprehensive tests for all REST API endpoints."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from database import db
from models import Campaign, Contact, Email, Reply, Metric


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_campaign(name='Test Campaign', status='draft'):
    """Create and return a Campaign."""
    c = Campaign(name=name, status=status)
    db.session.add(c)
    db.session.commit()
    return c


def _create_contact(campaign_id, name='Test User', email='test@example.com',
                     status='pending', wave=1, company='TestCo'):
    """Create and return a Contact."""
    c = Contact(
        campaign_id=campaign_id,
        name=name,
        email=email,
        status=status,
        wave=wave,
        company=company,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _create_email(contact_id, email_type='initial', subject='Hello',
                   body='Body text', status='draft'):
    """Create and return an Email."""
    e = Email(
        contact_id=contact_id,
        email_type=email_type,
        subject=subject,
        body=body,
        status=status,
    )
    db.session.add(e)
    db.session.commit()
    return e


def _create_reply(contact_id, from_email='user@example.com', snippet='Thanks!'):
    """Create and return a Reply."""
    r = Reply(
        contact_id=contact_id,
        from_email=from_email,
        snippet=snippet,
    )
    db.session.add(r)
    db.session.commit()
    return r


# ===========================================================================
# Campaign tests
# ===========================================================================

class TestCampaignEndpoints:

    def test_list_campaigns_empty(self, client, db):
        """GET /api/campaigns returns empty list when no campaigns exist."""
        resp = client.get('/api/campaigns')
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_create_campaign(self, client, db):
        """POST /api/campaigns creates a new campaign."""
        resp = client.post('/api/campaigns', json={
            'name': 'DC Outreach',
            'description': 'Data center cooling campaign',
            'max_emails_per_day': 8,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['name'] == 'DC Outreach'
        assert data['description'] == 'Data center cooling campaign'
        assert data['status'] == 'draft'
        assert data['max_emails_per_day'] == 8
        assert data['id'] is not None

    def test_create_campaign_requires_name(self, client, db):
        """POST /api/campaigns returns 400 without a name."""
        resp = client.post('/api/campaigns', json={'description': 'no name'})
        assert resp.status_code == 400

    def test_get_campaign(self, client, db):
        """GET /api/campaigns/<id> returns the campaign."""
        campaign = _create_campaign('Get Test')
        resp = client.get(f'/api/campaigns/{campaign.id}')
        assert resp.status_code == 200
        assert resp.get_json()['name'] == 'Get Test'

    def test_get_campaign_not_found(self, client, db):
        """GET /api/campaigns/<id> returns 404 for missing campaign."""
        resp = client.get('/api/campaigns/9999')
        assert resp.status_code == 404

    def test_update_campaign(self, client, db):
        """PUT /api/campaigns/<id> updates campaign fields."""
        campaign = _create_campaign('Original')
        resp = client.put(f'/api/campaigns/{campaign.id}', json={
            'name': 'Updated',
            'max_emails_per_day': 20,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['name'] == 'Updated'
        assert data['max_emails_per_day'] == 20

    def test_activate_campaign(self, client, db):
        """POST /api/campaigns/<id>/activate sets status to active."""
        campaign = _create_campaign('Activation Test')
        resp = client.post(f'/api/campaigns/{campaign.id}/activate')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'active'

    def test_pause_campaign(self, client, db):
        """POST /api/campaigns/<id>/pause sets status to paused."""
        campaign = _create_campaign('Pause Test', status='active')
        resp = client.post(f'/api/campaigns/{campaign.id}/pause')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'paused'

    def test_campaign_metrics(self, client, db):
        """GET /api/campaigns/<id>/metrics returns aggregate metrics."""
        campaign = _create_campaign('Metrics Campaign')
        contact = _create_contact(campaign.id)
        _create_email(contact.id, status='sent')
        _create_reply(contact.id)

        resp = client.get(f'/api/campaigns/{campaign.id}/metrics')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total_contacts'] == 1
        assert data['total_sent'] == 1
        assert data['total_replied'] == 1
        assert data['response_rate'] == 100.0


# ===========================================================================
# Contact tests
# ===========================================================================

class TestContactEndpoints:

    def test_list_contacts_empty(self, client, db):
        """GET /api/contacts returns empty list."""
        resp = client.get('/api/contacts')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['contacts'] == []
        assert data['total'] == 0

    def test_create_contact(self, client, db):
        """POST /api/contacts creates a single contact."""
        campaign = _create_campaign()
        resp = client.post('/api/contacts', json={
            'campaign_id': campaign.id,
            'name': 'Alice',
            'email': 'alice@example.com',
            'company': 'AcmeCo',
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['name'] == 'Alice'
        assert data['email'] == 'alice@example.com'
        assert data['company'] == 'AcmeCo'
        assert data['status'] == 'pending'

    def test_create_contact_requires_fields(self, client, db):
        """POST /api/contacts returns 400 without required fields."""
        resp = client.post('/api/contacts', json={'name': 'Bob'})
        assert resp.status_code == 400

    def test_get_contact_with_emails(self, client, db):
        """GET /api/contacts/<id> returns nested emails and replies."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        _create_email(contact.id, email_type='initial', subject='Hi')
        _create_email(contact.id, email_type='followup1', subject='Follow up')
        _create_reply(contact.id, snippet='Thanks for reaching out')

        resp = client.get(f'/api/contacts/{contact.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['name'] == 'Test User'
        assert len(data['emails']) == 2
        assert len(data['replies']) == 1
        assert data['replies'][0]['snippet'] == 'Thanks for reaching out'

    def test_get_contact_not_found(self, client, db):
        """GET /api/contacts/<id> returns 404 for missing contact."""
        resp = client.get('/api/contacts/9999')
        assert resp.status_code == 404

    def test_update_contact(self, client, db):
        """PUT /api/contacts/<id> updates contact fields."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id, name='OldName')
        resp = client.put(f'/api/contacts/{contact.id}', json={
            'name': 'NewName',
            'company': 'NewCo',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['name'] == 'NewName'
        assert data['company'] == 'NewCo'

    def test_delete_contact(self, client, db):
        """DELETE /api/contacts/<id> deletes contact and associated records."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        _create_email(contact.id)
        _create_reply(contact.id)

        resp = client.delete(f'/api/contacts/{contact.id}')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'deleted'

        # Verify gone
        assert db.session.get(Contact, contact.id) is None
        assert Email.query.filter_by(contact_id=contact.id).count() == 0
        assert Reply.query.filter_by(contact_id=contact.id).count() == 0

    def test_update_notes(self, client, db):
        """PUT /api/contacts/<id>/notes updates the notes field."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)

        resp = client.put(f'/api/contacts/{contact.id}/notes', json={
            'notes': 'Call scheduled for Friday',
        })
        assert resp.status_code == 200
        assert resp.get_json()['notes'] == 'Call scheduled for Friday'

    def test_opt_out_cancels_emails(self, client, db):
        """POST /api/contacts/<id>/opt-out marks opted_out and cancels emails."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        _create_email(contact.id, email_type='initial', status='draft')
        _create_email(contact.id, email_type='followup1', status='scheduled')
        _create_email(contact.id, email_type='followup2', status='sent')  # should NOT cancel

        resp = client.post(f'/api/contacts/{contact.id}/opt-out')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'opted_out'
        assert data['emails_cancelled'] == 2  # draft + scheduled, not sent

        # Verify the contact status
        refreshed = db.session.get(Contact, contact.id)
        assert refreshed.status == 'opted_out'

        # Verify emails
        emails = Email.query.filter_by(contact_id=contact.id).all()
        statuses = {e.email_type: e.status for e in emails}
        assert statuses['initial'] == 'cancelled'
        assert statuses['followup1'] == 'cancelled'
        assert statuses['followup2'] == 'sent'

    def test_bulk_create_contacts(self, client, db):
        """POST /api/contacts/bulk creates multiple contacts."""
        campaign = _create_campaign()
        resp = client.post('/api/contacts/bulk', json=[
            {
                'campaign_id': campaign.id,
                'name': 'Alice',
                'email': 'alice@example.com',
            },
            {
                'campaign_id': campaign.id,
                'name': 'Bob',
                'email': 'bob@example.com',
            },
        ])
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['total_created'] == 2
        assert len(data['created']) == 2
        assert data['errors'] == []

    def test_bulk_create_with_errors(self, client, db):
        """POST /api/contacts/bulk reports per-item errors."""
        campaign = _create_campaign()
        resp = client.post('/api/contacts/bulk', json=[
            {'campaign_id': campaign.id, 'name': 'Alice', 'email': 'a@b.com'},
            {'name': 'NoEmail'},  # missing campaign_id and email
        ])
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['total_created'] == 1
        assert len(data['errors']) == 1
        assert data['errors'][0]['index'] == 1

    def test_list_contacts_filter_by_status(self, client, db):
        """GET /api/contacts?status=pending filters correctly."""
        campaign = _create_campaign()
        _create_contact(campaign.id, name='A', email='a@b.com', status='pending')
        _create_contact(campaign.id, name='B', email='b@b.com', status='replied')

        resp = client.get('/api/contacts?status=pending')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 1
        assert data['contacts'][0]['name'] == 'A'

    def test_list_contacts_search(self, client, db):
        """GET /api/contacts?search=acme finds by company name."""
        campaign = _create_campaign()
        _create_contact(campaign.id, name='Alice', email='a@b.com', company='AcmeCo')
        _create_contact(campaign.id, name='Bob', email='b@b.com', company='ZetaCo')

        resp = client.get('/api/contacts?search=acme')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 1
        assert data['contacts'][0]['company'] == 'AcmeCo'

    def test_list_contacts_pagination(self, client, db):
        """GET /api/contacts with page and per_page paginates."""
        campaign = _create_campaign()
        for i in range(5):
            _create_contact(
                campaign.id, name=f'User{i}', email=f'u{i}@b.com'
            )

        resp = client.get('/api/contacts?page=2&per_page=2')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 5
        assert data['page'] == 2
        assert data['per_page'] == 2
        assert len(data['contacts']) == 2


# ===========================================================================
# Email tests
# ===========================================================================

class TestEmailEndpoints:

    def test_list_emails(self, client, db):
        """GET /api/emails returns all emails."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        _create_email(contact.id, email_type='initial')
        _create_email(contact.id, email_type='followup1')

        resp = client.get('/api/emails')
        assert resp.status_code == 200
        assert len(resp.get_json()) == 2

    def test_list_emails_filter_by_status(self, client, db):
        """GET /api/emails?status=draft filters correctly."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        _create_email(contact.id, status='draft')
        _create_email(contact.id, status='sent')

        resp = client.get('/api/emails?status=draft')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['status'] == 'draft'

    def test_get_email(self, client, db):
        """GET /api/emails/<id> returns the email."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        email = _create_email(contact.id, subject='Test Subject')

        resp = client.get(f'/api/emails/{email.id}')
        assert resp.status_code == 200
        assert resp.get_json()['subject'] == 'Test Subject'

    def test_get_email_not_found(self, client, db):
        """GET /api/emails/<id> returns 404 for missing email."""
        resp = client.get('/api/emails/9999')
        assert resp.status_code == 404

    def test_edit_email_draft(self, client, db):
        """PUT /api/emails/<id> edits subject and body for a draft."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        email = _create_email(contact.id, subject='Old', body='Old body')

        resp = client.put(f'/api/emails/{email.id}', json={
            'subject': 'New Subject',
            'body': 'New body text',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['subject'] == 'New Subject'
        assert data['body'] == 'New body text'

    def test_edit_email_rejects_sent(self, client, db):
        """PUT /api/emails/<id> returns 400 for sent emails."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        email = _create_email(contact.id, status='sent')

        resp = client.put(f'/api/emails/{email.id}', json={
            'subject': 'Cannot Edit',
        })
        assert resp.status_code == 400

    def test_cancel_scheduled_email(self, client, db):
        """POST /api/emails/<id>/cancel cancels a scheduled email."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        email = _create_email(contact.id, status='scheduled')

        resp = client.post(f'/api/emails/{email.id}/cancel')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'cancelled'

    def test_cancel_sent_email_fails(self, client, db):
        """POST /api/emails/<id>/cancel returns 400 for sent emails."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        email = _create_email(contact.id, status='sent')

        resp = client.post(f'/api/emails/{email.id}/cancel')
        assert resp.status_code == 400

    def test_get_queue(self, client, db):
        """GET /api/emails/queue returns the queue."""
        resp = client.get('/api/emails/queue')
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_generate_queue(self, client, db):
        """POST /api/emails/generate-queue schedules emails."""
        campaign = _create_campaign(status='active')
        contact = _create_contact(campaign.id, status='pending')
        _create_email(contact.id, email_type='initial', status='draft')

        resp = client.post('/api/emails/generate-queue', json={
            'campaign_id': campaign.id,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'scheduled' in data


# ===========================================================================
# Reply tests
# ===========================================================================

class TestReplyEndpoints:

    def test_list_replies(self, client, db):
        """GET /api/replies returns all replies."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        _create_reply(contact.id, snippet='Reply 1')
        _create_reply(contact.id, snippet='Reply 2')

        resp = client.get('/api/replies')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_replies_for_contact(self, client, db):
        """GET /api/replies/contact/<id> returns replies for that contact."""
        campaign = _create_campaign()
        c1 = _create_contact(campaign.id, name='A', email='a@b.com')
        c2 = _create_contact(campaign.id, name='B', email='b@b.com')
        _create_reply(c1.id, snippet='Reply for A')
        _create_reply(c2.id, snippet='Reply for B')

        resp = client.get(f'/api/replies/contact/{c1.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['snippet'] == 'Reply for A'

    def test_replies_for_missing_contact(self, client, db):
        """GET /api/replies/contact/<id> returns 404 for missing contact."""
        resp = client.get('/api/replies/contact/9999')
        assert resp.status_code == 404


# ===========================================================================
# Metrics / Dashboard tests
# ===========================================================================

class TestMetricsEndpoints:

    def test_dashboard_metrics_empty(self, client, db):
        """GET /api/metrics/dashboard returns zeroed metrics when DB empty."""
        resp = client.get('/api/metrics/dashboard')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total_contacts'] == 0
        assert data['total_sent'] == 0
        assert data['total_replied'] == 0
        assert data['response_rate'] == 0.0

    def test_dashboard_metrics_with_data(self, client, db):
        """GET /api/metrics/dashboard computes correct metrics with data."""
        campaign = _create_campaign()
        c1 = _create_contact(campaign.id, name='A', email='a@b.com', status='replied')
        c2 = _create_contact(campaign.id, name='B', email='b@b.com', status='initial_sent')

        now = datetime.now(timezone.utc)

        # Sent emails
        e1 = Email(
            contact_id=c1.id, email_type='initial', subject='Hi A',
            body='body', status='sent', sent_at=now - timedelta(hours=48),
        )
        e2 = Email(
            contact_id=c2.id, email_type='initial', subject='Hi B',
            body='body', status='sent', sent_at=now - timedelta(hours=24),
        )
        e3 = Email(
            contact_id=c1.id, email_type='followup1', subject='FU1',
            body='body', status='draft',
        )
        db.session.add_all([e1, e2, e3])

        # A reply from contact A
        r = Reply(
            contact_id=c1.id, from_email='a@b.com',
            snippet='Thanks!', received_at=now - timedelta(hours=24),
        )
        db.session.add(r)
        db.session.commit()

        resp = client.get('/api/metrics/dashboard')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total_contacts'] == 2
        assert data['total_sent'] == 2
        assert data['total_replied'] == 1
        assert data['response_rate'] == 50.0
        assert 'emails_by_status' in data
        assert 'contacts_by_status' in data
        assert data['emails_by_status']['sent'] == 2
        assert data['emails_by_status']['draft'] == 1

    def test_contact_metrics(self, client, db):
        """GET /api/metrics/contacts/<id> returns per-contact metrics."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)
        m = Metric(
            contact_id=contact.id, metric_type='sent', value='initial',
        )
        db.session.add(m)
        db.session.commit()

        resp = client.get(f'/api/metrics/contacts/{contact.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['contact_id'] == contact.id
        assert len(data['metrics']) == 1
        assert data['metrics'][0]['metric_type'] == 'sent'

    def test_contact_metrics_not_found(self, client, db):
        """GET /api/metrics/contacts/<id> returns 404 for missing contact."""
        resp = client.get('/api/metrics/contacts/9999')
        assert resp.status_code == 404


# ===========================================================================
# Dashboard HTML routes (render templates)
# ===========================================================================

class TestDashboardRoutes:

    def test_index_returns_html(self, client, db):
        """GET / returns the dashboard HTML page."""
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'Dashboard' in resp.data
        assert b'text/html' in resp.content_type.encode()

    def test_contact_list_page(self, client, db):
        """GET /contacts returns the contacts list HTML page."""
        resp = client.get('/contacts')
        assert resp.status_code == 200
        assert b'Contacts' in resp.data
        assert b'text/html' in resp.content_type.encode()

    def test_contact_detail_page(self, client, db):
        """GET /contacts/<id> returns the contact detail HTML page."""
        campaign = _create_campaign()
        contact = _create_contact(campaign.id)

        resp = client.get(f'/contacts/{contact.id}')
        assert resp.status_code == 200
        assert b'Contact Detail' in resp.data

    def test_contact_detail_not_found(self, client, db):
        """GET /contacts/<id> returns 404 for missing contact."""
        resp = client.get('/contacts/9999')
        assert resp.status_code == 404

    def test_campaigns_page(self, client, db):
        """GET /campaigns returns the campaigns list HTML page."""
        resp = client.get('/campaigns')
        assert resp.status_code == 200
        assert b'Campaigns' in resp.data

    def test_settings_page(self, client, db):
        """GET /settings returns the settings HTML page."""
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert b'Settings' in resp.data

    def test_email_queue_page(self, client, db):
        """GET /emails/queue returns the email queue HTML page."""
        resp = client.get('/emails/queue')
        assert resp.status_code == 200
        assert b'Email Queue' in resp.data

    def test_reports_page(self, client, db):
        """GET /reports returns the reports HTML page."""
        resp = client.get('/reports')
        assert resp.status_code == 200
        assert b'Reports' in resp.data

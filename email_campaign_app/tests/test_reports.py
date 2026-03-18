"""Comprehensive tests for report generation and report API endpoints."""

import os
import json
from datetime import datetime, timedelta, timezone

import pytest

from database import db
from models import Campaign, Contact, Email, Reply, Metric, Report


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
                     status='pending', wave=1, company='TestCo', notes=None):
    """Create and return a Contact."""
    c = Contact(
        campaign_id=campaign_id,
        name=name,
        email=email,
        status=status,
        wave=wave,
        company=company,
        notes=notes,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _create_email(contact_id, email_type='initial', subject='Hello',
                   body='Body text', status='draft', sent_at=None):
    """Create and return an Email."""
    e = Email(
        contact_id=contact_id,
        email_type=email_type,
        subject=subject,
        body=body,
        status=status,
        sent_at=sent_at,
    )
    db.session.add(e)
    db.session.commit()
    return e


def _create_reply(contact_id, from_email='user@example.com',
                   snippet='Thanks!', received_at=None):
    """Create and return a Reply."""
    r = Reply(
        contact_id=contact_id,
        from_email=from_email,
        snippet=snippet,
        received_at=received_at or datetime.now(timezone.utc),
    )
    db.session.add(r)
    db.session.commit()
    return r


def _build_campaign_with_data():
    """Build a campaign with contacts, emails, and replies for testing.

    Returns (campaign, contacts_list).
    """
    now = datetime.now(timezone.utc)
    campaign = _create_campaign('Outreach Test', status='active')

    # Wave 1: 2 contacts
    c1 = _create_contact(
        campaign.id, name='Alice Smith', email='alice@example.com',
        status='replied', wave=1, company='AlphaCo',
        notes='Very interested in product',
    )
    c2 = _create_contact(
        campaign.id, name='Bob Jones', email='bob@example.com',
        status='initial_sent', wave=1, company='BetaCo',
    )

    # Wave 2: 2 contacts
    c3 = _create_contact(
        campaign.id, name='Carol White', email='carol@example.com',
        status='followup1_sent', wave=2, company='GammaCo',
    )
    c4 = _create_contact(
        campaign.id, name='Dave Brown', email='dave@example.com',
        status='pending', wave=2, company='DeltaCo',
    )

    # Emails for Alice (initial sent, got reply)
    e1 = _create_email(
        c1.id, email_type='initial', subject='Hi Alice',
        status='sent', sent_at=now - timedelta(hours=48),
    )

    # Emails for Bob (initial sent, no reply)
    e2 = _create_email(
        c2.id, email_type='initial', subject='Hi Bob',
        status='sent', sent_at=now - timedelta(hours=72),
    )

    # Emails for Carol (initial + followup1 sent)
    e3 = _create_email(
        c3.id, email_type='initial', subject='Hi Carol',
        status='sent', sent_at=now - timedelta(hours=120),
    )
    e4 = _create_email(
        c3.id, email_type='followup1', subject='FU1 Carol',
        status='sent', sent_at=now - timedelta(hours=48),
    )

    # Reply from Alice
    _create_reply(
        c1.id, from_email='alice@example.com',
        snippet='Sure, happy to discuss!',
        received_at=now - timedelta(hours=24),
    )

    return campaign, [c1, c2, c3, c4]


# ===========================================================================
# Campaign report generation tests
# ===========================================================================

class TestGenerateCampaignReport:

    def test_generate_campaign_report_creates_record(self, app, db):
        """Report record is created in the database."""
        with app.app_context():
            campaign, _ = _build_campaign_with_data()
            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)

            assert report.id is not None
            assert report.campaign_id == campaign.id
            assert report.report_type == 'campaign_summary'
            assert report.content is not None
            assert len(report.content) > 0

            # Verify it's in the DB
            fetched = db.session.get(Report, report.id)
            assert fetched is not None
            assert fetched.filename.endswith('.md')

    def test_generate_campaign_report_writes_file(self, app, db):
        """Report file is written to the reports/ directory."""
        with app.app_context():
            campaign, _ = _build_campaign_with_data()
            from routes.reports import generate_campaign_report, REPORTS_DIR
            report = generate_campaign_report(campaign.id)

            filepath = os.path.join(REPORTS_DIR, report.filename)
            assert os.path.exists(filepath)

            with open(filepath) as f:
                file_content = f.read()
            assert file_content == report.content

            # Cleanup
            os.remove(filepath)

    def test_generate_campaign_report_contains_summary(self, app, db):
        """Summary section contains correct counts."""
        with app.app_context():
            campaign, contacts = _build_campaign_with_data()
            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)
            content = report.content

            assert '## Summary' in content
            assert 'Total contacts: 4' in content
            assert 'Replies received: 1' in content
            # 3 sent emails (Alice initial, Bob initial, Carol initial)
            # Plus Carol FU1 = 4 total sent
            assert 'Emails sent: 4' in content
            assert 'Still pending: 1' in content

    def test_generate_campaign_report_per_wave(self, app, db):
        """Per-wave breakdown is present and accurate."""
        with app.app_context():
            campaign, _ = _build_campaign_with_data()
            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)
            content = report.content

            assert '## Per-Wave Performance' in content
            # Wave 1 has 2 contacts
            assert '| 1 | 2 |' in content
            # Wave 2 has 2 contacts
            assert '| 2 | 2 |' in content

    def test_generate_campaign_report_top_responders(self, app, db):
        """Top responders section lists replied contacts sorted by response time."""
        with app.app_context():
            campaign, _ = _build_campaign_with_data()
            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)
            content = report.content

            assert '## Top Responders' in content
            assert 'Alice Smith' in content
            assert 'AlphaCo' in content
            assert 'happy to discuss' in content

    def test_generate_campaign_report_contacts_waiting(self, app, db):
        """Contacts still waiting section lists non-replied contacts."""
        with app.app_context():
            campaign, _ = _build_campaign_with_data()
            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)
            content = report.content

            assert '## Contacts Still Waiting' in content
            assert 'Bob Jones' in content
            assert 'Carol White' in content
            # Dave is pending (not yet sent), so NOT in waiting
            assert 'Dave Brown' not in content.split('## Contacts Still Waiting')[1].split('##')[0] if '## Contacts Still Waiting' in content else True

    def test_generate_campaign_report_empty_campaign(self, app, db):
        """Handles campaign with no contacts gracefully."""
        with app.app_context():
            campaign = _create_campaign('Empty Campaign')
            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)

            assert report.id is not None
            assert 'Total contacts: 0' in report.content
            assert 'Response rate: 0.0%' in report.content

            # Cleanup file
            from routes.reports import REPORTS_DIR
            filepath = os.path.join(REPORTS_DIR, report.filename)
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_generate_campaign_report_email_performance(self, app, db):
        """Email performance by type section is present."""
        with app.app_context():
            campaign, _ = _build_campaign_with_data()
            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)
            content = report.content

            assert '## Email Performance by Type' in content
            assert 'Initial' in content
            assert 'Follow-Up 1' in content
            assert 'Follow-Up 2' in content

            # Cleanup
            from routes.reports import REPORTS_DIR
            filepath = os.path.join(REPORTS_DIR, report.filename)
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_generate_campaign_report_recommendations(self, app, db):
        """Recommendations section is generated."""
        with app.app_context():
            campaign, _ = _build_campaign_with_data()
            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)
            content = report.content

            assert '## Recommendations' in content
            # Should recommend scheduling remaining initials (Dave is pending)
            assert 'haven\'t been reached yet' in content

            # Cleanup
            from routes.reports import REPORTS_DIR
            filepath = os.path.join(REPORTS_DIR, report.filename)
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_generate_campaign_report_notes(self, app, db):
        """Campaign notes section includes contact notes."""
        with app.app_context():
            campaign, _ = _build_campaign_with_data()
            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)
            content = report.content

            assert '## Campaign Notes' in content
            assert 'Very interested in product' in content

            # Cleanup
            from routes.reports import REPORTS_DIR
            filepath = os.path.join(REPORTS_DIR, report.filename)
            if os.path.exists(filepath):
                os.remove(filepath)


# ===========================================================================
# Daily summary tests
# ===========================================================================

class TestGenerateDailySummary:

    def test_generate_daily_summary(self, app, db):
        """Daily summary has today's activity sections."""
        with app.app_context():
            now = datetime.now(timezone.utc)
            campaign = _create_campaign('Daily Test', status='active')
            c1 = _create_contact(
                campaign.id, name='Eve', email='eve@example.com',
                status='initial_sent', wave=1, company='EpsilonCo',
            )
            # Sent today
            _create_email(
                c1.id, email_type='initial', subject='Hi Eve',
                status='sent', sent_at=now - timedelta(hours=2),
            )
            # Reply today
            _create_reply(
                c1.id, from_email='eve@example.com',
                snippet='Looks great!',
                received_at=now - timedelta(hours=1),
            )

            from routes.reports import generate_daily_summary
            report = generate_daily_summary(campaign.id)

            assert report.report_type == 'daily_summary'
            content = report.content
            assert '# Daily Summary:' in content
            assert "## Today's Activity" in content
            assert 'Emails sent: 1' in content
            assert 'Replies received: 1' in content

            # Cleanup
            from routes.reports import REPORTS_DIR
            filepath = os.path.join(REPORTS_DIR, report.filename)
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_generate_daily_summary_empty(self, app, db):
        """Daily summary handles no activity gracefully."""
        with app.app_context():
            campaign = _create_campaign('Empty Daily', status='active')
            from routes.reports import generate_daily_summary
            report = generate_daily_summary(campaign.id)

            assert 'Emails sent: 0' in report.content
            assert 'Replies received: 0' in report.content

            # Cleanup
            from routes.reports import REPORTS_DIR
            filepath = os.path.join(REPORTS_DIR, report.filename)
            if os.path.exists(filepath):
                os.remove(filepath)


# ===========================================================================
# API endpoint tests
# ===========================================================================

class TestReportAPIEndpoints:

    def test_api_generate_report(self, client, db):
        """POST /api/reports/generate returns 201 with report data."""
        campaign = _create_campaign('API Test')
        _create_contact(campaign.id)

        resp = client.post('/api/reports/generate', json={
            'campaign_id': campaign.id,
            'report_type': 'campaign_summary',
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['campaign_id'] == campaign.id
        assert data['report_type'] == 'campaign_summary'
        assert data['content'] is not None
        assert '## Summary' in data['content']

        # Cleanup
        from routes.reports import REPORTS_DIR
        filepath = os.path.join(REPORTS_DIR, data['filename'])
        if os.path.exists(filepath):
            os.remove(filepath)

    def test_api_generate_report_missing_campaign(self, client, db):
        """POST /api/reports/generate returns 404 for missing campaign."""
        resp = client.post('/api/reports/generate', json={
            'campaign_id': 9999,
        })
        assert resp.status_code == 404

    def test_api_generate_report_missing_campaign_id(self, client, db):
        """POST /api/reports/generate returns 400 without campaign_id."""
        resp = client.post('/api/reports/generate', json={})
        assert resp.status_code == 400

    def test_api_list_reports(self, client, db):
        """GET /api/reports returns list of reports."""
        campaign = _create_campaign('List Test')
        r1 = Report(
            campaign_id=campaign.id, report_type='campaign_summary',
            content='# Report 1', filename='r1.md',
        )
        r2 = Report(
            campaign_id=campaign.id, report_type='daily_summary',
            content='# Report 2', filename='r2.md',
        )
        db.session.add_all([r1, r2])
        db.session.commit()

        resp = client.get('/api/reports')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        # Content should NOT be in list view
        assert 'content' not in data[0]

    def test_api_list_reports_filter_by_campaign(self, client, db):
        """GET /api/reports?campaign_id=N filters correctly."""
        c1 = _create_campaign('C1')
        c2 = _create_campaign('C2')
        r1 = Report(
            campaign_id=c1.id, report_type='campaign_summary',
            content='# R1', filename='r1.md',
        )
        r2 = Report(
            campaign_id=c2.id, report_type='campaign_summary',
            content='# R2', filename='r2.md',
        )
        db.session.add_all([r1, r2])
        db.session.commit()

        resp = client.get(f'/api/reports?campaign_id={c1.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['campaign_id'] == c1.id

    def test_api_get_report(self, client, db):
        """GET /api/reports/<id> returns report with content."""
        campaign = _create_campaign('Get Test')
        report = Report(
            campaign_id=campaign.id, report_type='campaign_summary',
            content='# Full Report Content', filename='report.md',
        )
        db.session.add(report)
        db.session.commit()

        resp = client.get(f'/api/reports/{report.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['content'] == '# Full Report Content'
        assert data['id'] == report.id

    def test_api_get_report_not_found(self, client, db):
        """GET /api/reports/<id> returns 404 for missing report."""
        resp = client.get('/api/reports/9999')
        assert resp.status_code == 404

    def test_api_download_report(self, client, db):
        """GET /api/reports/<id>/download returns markdown file."""
        campaign = _create_campaign('Download Test')

        from routes.reports import REPORTS_DIR
        os.makedirs(REPORTS_DIR, exist_ok=True)

        filename = 'test_download_report.md'
        filepath = os.path.join(REPORTS_DIR, filename)
        with open(filepath, 'w') as f:
            f.write('# Test Report Download')

        report = Report(
            campaign_id=campaign.id, report_type='campaign_summary',
            content='# Test Report Download', filename=filename,
        )
        db.session.add(report)
        db.session.commit()

        resp = client.get(f'/api/reports/{report.id}/download')
        assert resp.status_code == 200
        assert b'# Test Report Download' in resp.data
        assert 'text/markdown' in resp.content_type

        # Cleanup
        if os.path.exists(filepath):
            os.remove(filepath)

    def test_api_download_report_not_found(self, client, db):
        """GET /api/reports/<id>/download returns 404 for missing report."""
        resp = client.get('/api/reports/9999/download')
        assert resp.status_code == 404


# ===========================================================================
# Metrics calculation tests
# ===========================================================================

class TestMetricsCalculation:

    def test_metrics_response_rate_calculation(self, app, db):
        """Verify response rate = replied_contacts / initial_sends * 100."""
        with app.app_context():
            now = datetime.now(timezone.utc)
            campaign = _create_campaign('Rate Test')

            # 4 contacts: 3 get initials sent, 1 replies
            c1 = _create_contact(
                campaign.id, name='A', email='a@b.com',
                status='replied', wave=1,
            )
            c2 = _create_contact(
                campaign.id, name='B', email='b@b.com',
                status='initial_sent', wave=1,
            )
            c3 = _create_contact(
                campaign.id, name='C', email='c@b.com',
                status='initial_sent', wave=1,
            )
            c4 = _create_contact(
                campaign.id, name='D', email='d@b.com',
                status='pending', wave=2,
            )

            # Send initials for c1, c2, c3
            for c in [c1, c2, c3]:
                _create_email(
                    c.id, email_type='initial', subject=f'Hi {c.name}',
                    status='sent', sent_at=now - timedelta(hours=48),
                )

            # Reply from c1 only
            _create_reply(
                c1.id, from_email='a@b.com', snippet='Yes!',
                received_at=now - timedelta(hours=24),
            )

            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)

            # Response rate = 1 replied / 3 initials sent = 33.3%
            assert 'Response rate: 33.3%' in report.content

            # Cleanup
            from routes.reports import REPORTS_DIR
            filepath = os.path.join(REPORTS_DIR, report.filename)
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_metrics_avg_response_time(self, app, db):
        """Verify average response time calculation."""
        with app.app_context():
            now = datetime.now(timezone.utc)
            campaign = _create_campaign('Time Test')

            # Contact 1: replied 24 hours after initial
            c1 = _create_contact(
                campaign.id, name='Fast', email='fast@b.com',
                status='replied', wave=1,
            )
            _create_email(
                c1.id, email_type='initial', subject='Hi',
                status='sent', sent_at=now - timedelta(hours=48),
            )
            _create_reply(
                c1.id, from_email='fast@b.com', snippet='Quick reply',
                received_at=now - timedelta(hours=24),
            )

            # Contact 2: replied 72 hours after initial
            c2 = _create_contact(
                campaign.id, name='Slow', email='slow@b.com',
                status='replied', wave=1,
            )
            _create_email(
                c2.id, email_type='initial', subject='Hi',
                status='sent', sent_at=now - timedelta(hours=96),
            )
            _create_reply(
                c2.id, from_email='slow@b.com', snippet='Slow reply',
                received_at=now - timedelta(hours=24),
            )

            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)

            # Avg = (24 + 72) / 2 = 48 hours = 2.0 days
            assert 'Average response time: 48.0 hours' in report.content
            assert '2.0 days' in report.content

            # Cleanup
            from routes.reports import REPORTS_DIR
            filepath = os.path.join(REPORTS_DIR, report.filename)
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_metrics_contact_status_breakdown(self, app, db):
        """Verify contact status breakdown table."""
        with app.app_context():
            campaign = _create_campaign('Status Test')
            _create_contact(
                campaign.id, name='A', email='a@b.com', status='pending',
            )
            _create_contact(
                campaign.id, name='B', email='b@b.com', status='pending',
            )
            _create_contact(
                campaign.id, name='C', email='c@b.com', status='replied',
            )

            from routes.reports import generate_campaign_report
            report = generate_campaign_report(campaign.id)

            assert '## Contact Status Breakdown' in report.content
            assert '| pending | 2 | 67% |' in report.content
            assert '| replied | 1 | 33% |' in report.content

            # Cleanup
            from routes.reports import REPORTS_DIR
            filepath = os.path.join(REPORTS_DIR, report.filename)
            if os.path.exists(filepath):
                os.remove(filepath)


# ===========================================================================
# Scheduler integration test
# ===========================================================================

class TestSchedulerIntegration:

    def test_daily_report_job_function_exists(self, app, db):
        """The daily report job function is importable and callable."""
        from scheduler.jobs import generate_daily_report_job
        assert callable(generate_daily_report_job)

    def test_generate_daily_summary_via_api(self, client, db):
        """POST /api/reports/generate with daily_summary type works."""
        campaign = _create_campaign('Daily API Test')

        resp = client.post('/api/reports/generate', json={
            'campaign_id': campaign.id,
            'report_type': 'daily_summary',
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['report_type'] == 'daily_summary'
        assert '# Daily Summary:' in data['content']

        # Cleanup
        from routes.reports import REPORTS_DIR
        filepath = os.path.join(REPORTS_DIR, data['filename'])
        if os.path.exists(filepath):
            os.remove(filepath)

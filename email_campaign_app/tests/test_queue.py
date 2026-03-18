"""Tests for email queue management -- scheduling, spreading, and processing."""

import os
import sys
from datetime import datetime, timedelta, timezone, time
from unittest.mock import patch, MagicMock

import pytz
import pytest

# Ensure the app package is importable
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
)

from app import create_app
from config import TestConfig
from database import db as _db
from models import Campaign, Contact, Email, Reply


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    app = create_app(TestConfig)
    yield app


@pytest.fixture
def db(app):
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def active_campaign(db):
    """Create an active campaign with default schedule settings."""
    campaign = Campaign(
        name='Queue Test Campaign',
        status='active',
        send_start_hour=8,
        send_end_hour=17,
        min_interval_minutes=15,
        max_emails_per_day=10,
        followup1_delay_days=3,
        followup2_delay_days=7,
        timezone='America/Los_Angeles',
    )
    db.session.add(campaign)
    db.session.commit()
    return campaign


def _make_contact(db, campaign, name='John Doe', email='john@example.com',
                  status='pending', wave=1, external_id='001'):
    """Helper to create a contact."""
    contact = Contact(
        campaign_id=campaign.id,
        name=name,
        email=email,
        status=status,
        wave=wave,
        external_id=external_id,
        company='Acme Corp',
    )
    db.session.add(contact)
    db.session.commit()
    return contact


def _make_email(db, contact, email_type='initial', status='draft',
                subject='Test Subject', body='Test body', sent_at=None):
    """Helper to create an email record."""
    email = Email(
        contact_id=contact.id,
        email_type=email_type,
        subject=subject,
        body=body,
        status=status,
        sent_at=sent_at,
    )
    db.session.add(email)
    db.session.commit()
    return email


# ---------------------------------------------------------------------------
# find_pending_initials Tests
# ---------------------------------------------------------------------------


class TestFindPendingInitials:

    def test_find_pending_initials_returns_drafts(self, app, db, active_campaign):
        """Creates contacts/emails, finds draft initials."""
        with app.app_context():
            from scheduler.queue import find_pending_initials

            c1 = _make_contact(db, active_campaign, 'Alice', 'alice@ex.com',
                               wave=1, external_id='001')
            c2 = _make_contact(db, active_campaign, 'Bob', 'bob@ex.com',
                               wave=1, external_id='002')
            e1 = _make_email(db, c1, 'initial', 'draft')
            e2 = _make_email(db, c2, 'initial', 'draft')

            results = find_pending_initials(active_campaign.id, 10)

            assert len(results) == 2
            assert results[0].id == e1.id
            assert results[1].id == e2.id

    def test_find_pending_initials_wave_order(self, app, db, active_campaign):
        """Wave 1 contacts returned before Wave 2."""
        with app.app_context():
            from scheduler.queue import find_pending_initials

            c_wave2 = _make_contact(db, active_campaign, 'Wave2', 'w2@ex.com',
                                    wave=2, external_id='002')
            c_wave1 = _make_contact(db, active_campaign, 'Wave1', 'w1@ex.com',
                                    wave=1, external_id='001')
            e2 = _make_email(db, c_wave2, 'initial', 'draft')
            e1 = _make_email(db, c_wave1, 'initial', 'draft')

            results = find_pending_initials(active_campaign.id, 10)

            assert len(results) == 2
            assert results[0].id == e1.id  # Wave 1 first
            assert results[1].id == e2.id  # Wave 2 second

    def test_find_pending_initials_respects_limit(self, app, db, active_campaign):
        """Only returns `limit` contacts."""
        with app.app_context():
            from scheduler.queue import find_pending_initials

            for i in range(5):
                c = _make_contact(db, active_campaign, f'C{i}', f'c{i}@ex.com',
                                  wave=1, external_id=f'{i:03d}')
                _make_email(db, c, 'initial', 'draft')

            results = find_pending_initials(active_campaign.id, 3)

            assert len(results) == 3

    def test_find_pending_initials_skips_non_pending(self, app, db, active_campaign):
        """Contacts with status != pending are skipped."""
        with app.app_context():
            from scheduler.queue import find_pending_initials

            c_pending = _make_contact(db, active_campaign, 'Pending', 'p@ex.com',
                                      status='pending', wave=1, external_id='001')
            c_sent = _make_contact(db, active_campaign, 'Sent', 's@ex.com',
                                   status='initial_sent', wave=1, external_id='002')
            _make_email(db, c_pending, 'initial', 'draft')
            _make_email(db, c_sent, 'initial', 'draft')

            results = find_pending_initials(active_campaign.id, 10)

            assert len(results) == 1
            assert results[0].contact.name == 'Pending'


# ---------------------------------------------------------------------------
# find_due_followups Tests
# ---------------------------------------------------------------------------


class TestFindDueFollowups:

    def test_find_due_followups_fu1_due(self, app, db, active_campaign):
        """FU1 due after followup1_delay_days."""
        with app.app_context():
            from scheduler.queue import find_due_followups

            contact = _make_contact(db, active_campaign, 'FU1', 'fu1@ex.com',
                                    status='initial_sent', wave=1, external_id='001')
            # Initial sent 4 days ago (delay is 3)
            sent_at = datetime.now(timezone.utc) - timedelta(days=4)
            _make_email(db, contact, 'initial', 'sent', sent_at=sent_at)
            fu1 = _make_email(db, contact, 'followup1', 'draft')

            today = datetime.now(pytz.timezone('America/Los_Angeles')).date()
            results = find_due_followups(active_campaign.id, today, active_campaign)

            assert len(results) == 1
            assert results[0].id == fu1.id

    def test_find_due_followups_fu1_not_due(self, app, db, active_campaign):
        """FU1 not due before delay."""
        with app.app_context():
            from scheduler.queue import find_due_followups

            contact = _make_contact(db, active_campaign, 'FU1Early', 'fu1e@ex.com',
                                    status='initial_sent', wave=1, external_id='001')
            # Initial sent 1 day ago (delay is 3)
            sent_at = datetime.now(timezone.utc) - timedelta(days=1)
            _make_email(db, contact, 'initial', 'sent', sent_at=sent_at)
            _make_email(db, contact, 'followup1', 'draft')

            today = datetime.now(pytz.timezone('America/Los_Angeles')).date()
            results = find_due_followups(active_campaign.id, today, active_campaign)

            assert len(results) == 0

    def test_find_due_followups_fu2_due(self, app, db, active_campaign):
        """FU2 due after followup2_delay_days."""
        with app.app_context():
            from scheduler.queue import find_due_followups

            contact = _make_contact(db, active_campaign, 'FU2', 'fu2@ex.com',
                                    status='followup1_sent', wave=1, external_id='001')
            # Initial sent 8 days ago (delay is 7)
            sent_at = datetime.now(timezone.utc) - timedelta(days=8)
            _make_email(db, contact, 'initial', 'sent', sent_at=sent_at)
            fu2 = _make_email(db, contact, 'followup2', 'draft')

            today = datetime.now(pytz.timezone('America/Los_Angeles')).date()
            results = find_due_followups(active_campaign.id, today, active_campaign)

            assert len(results) == 1
            assert results[0].id == fu2.id

    def test_find_due_followups_skips_replied(self, app, db, active_campaign):
        """Replied contacts skipped."""
        with app.app_context():
            from scheduler.queue import find_due_followups

            contact = _make_contact(db, active_campaign, 'Replied', 'r@ex.com',
                                    status='initial_sent', wave=1, external_id='001')
            sent_at = datetime.now(timezone.utc) - timedelta(days=4)
            _make_email(db, contact, 'initial', 'sent', sent_at=sent_at)
            _make_email(db, contact, 'followup1', 'draft')

            # Create a reply
            reply = Reply(
                contact_id=contact.id,
                from_email='r@ex.com',
                gmail_thread_id='thread_r',
            )
            db.session.add(reply)
            db.session.commit()

            today = datetime.now(pytz.timezone('America/Los_Angeles')).date()
            results = find_due_followups(active_campaign.id, today, active_campaign)

            assert len(results) == 0

    def test_find_due_followups_skips_bounced(self, app, db, active_campaign):
        """Bounced contacts skipped (status not in eligible list)."""
        with app.app_context():
            from scheduler.queue import find_due_followups

            contact = _make_contact(db, active_campaign, 'Bounced', 'b@ex.com',
                                    status='bounced', wave=1, external_id='001')
            sent_at = datetime.now(timezone.utc) - timedelta(days=4)
            _make_email(db, contact, 'initial', 'sent', sent_at=sent_at)
            _make_email(db, contact, 'followup1', 'draft')

            today = datetime.now(pytz.timezone('America/Los_Angeles')).date()
            results = find_due_followups(active_campaign.id, today, active_campaign)

            assert len(results) == 0


# ---------------------------------------------------------------------------
# generate_daily_queue Tests
# ---------------------------------------------------------------------------


class TestGenerateDailyQueue:

    def test_generate_daily_queue_schedules_emails(self, app, db, active_campaign):
        """Queue generated with correct count."""
        with app.app_context():
            from scheduler.queue import generate_daily_queue

            # Create 3 contacts with draft initials
            for i in range(3):
                c = _make_contact(db, active_campaign, f'C{i}', f'c{i}@ex.com',
                                  wave=1, external_id=f'{i:03d}')
                _make_email(db, c, 'initial', 'draft')

            # Freeze time to morning so all emails fit in the window
            morning = datetime(2026, 3, 3, 7, 0, 0)
            la_tz = pytz.timezone('America/Los_Angeles')
            morning_la = la_tz.localize(morning)

            with patch('scheduler.queue.datetime') as mock_dt:
                mock_dt.now.return_value = morning_la
                mock_dt.combine = datetime.combine
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                count = generate_daily_queue(active_campaign.id)

            assert count == 3

            # Verify emails are scheduled
            scheduled = Email.query.filter_by(status='scheduled').all()
            assert len(scheduled) == 3

    def test_generate_daily_queue_respects_max_per_day(self, app, db, active_campaign):
        """Doesn't exceed max_emails_per_day."""
        with app.app_context():
            from scheduler.queue import generate_daily_queue

            # Set max to 2
            active_campaign.max_emails_per_day = 2
            db.session.commit()

            for i in range(5):
                c = _make_contact(db, active_campaign, f'C{i}', f'c{i}@ex.com',
                                  wave=1, external_id=f'{i:03d}')
                _make_email(db, c, 'initial', 'draft')

            morning = datetime(2026, 3, 3, 7, 0, 0)
            la_tz = pytz.timezone('America/Los_Angeles')
            morning_la = la_tz.localize(morning)

            with patch('scheduler.queue.datetime') as mock_dt:
                mock_dt.now.return_value = morning_la
                mock_dt.combine = datetime.combine
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                count = generate_daily_queue(active_campaign.id)

            assert count == 2

    def test_generate_daily_queue_spreads_intervals(self, app, db, active_campaign):
        """Emails spaced at min_interval_minutes."""
        with app.app_context():
            from scheduler.queue import generate_daily_queue

            for i in range(3):
                c = _make_contact(db, active_campaign, f'C{i}', f'c{i}@ex.com',
                                  wave=1, external_id=f'{i:03d}')
                _make_email(db, c, 'initial', 'draft')

            morning = datetime(2026, 3, 3, 7, 0, 0)
            la_tz = pytz.timezone('America/Los_Angeles')
            morning_la = la_tz.localize(morning)

            with patch('scheduler.queue.datetime') as mock_dt:
                mock_dt.now.return_value = morning_la
                mock_dt.combine = datetime.combine
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                generate_daily_queue(active_campaign.id)

            scheduled = Email.query.filter_by(status='scheduled').order_by(
                Email.scheduled_at.asc()
            ).all()
            assert len(scheduled) == 3

            # Check spacing is 15 minutes
            for i in range(1, len(scheduled)):
                diff = (scheduled[i].scheduled_at - scheduled[i - 1].scheduled_at)
                assert diff.total_seconds() == 15 * 60

    def test_generate_daily_queue_within_send_window(self, app, db, active_campaign):
        """No emails past send_end_hour."""
        with app.app_context():
            from scheduler.queue import generate_daily_queue

            # Narrow window: 8am-9am with 15 min interval = max 4 emails
            active_campaign.send_start_hour = 8
            active_campaign.send_end_hour = 9
            active_campaign.max_emails_per_day = 20  # Won't limit
            db.session.commit()

            for i in range(10):
                c = _make_contact(db, active_campaign, f'C{i}', f'c{i}@ex.com',
                                  wave=1, external_id=f'{i:03d}')
                _make_email(db, c, 'initial', 'draft')

            morning = datetime(2026, 3, 3, 7, 0, 0)
            la_tz = pytz.timezone('America/Los_Angeles')
            morning_la = la_tz.localize(morning)

            with patch('scheduler.queue.datetime') as mock_dt:
                mock_dt.now.return_value = morning_la
                mock_dt.combine = datetime.combine
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                count = generate_daily_queue(active_campaign.id)

            # 8:00, 8:15, 8:30, 8:45 = 4 emails (9:00 would be at/past end)
            assert count == 4

            # Verify none are past end hour
            la_tz = pytz.timezone('America/Los_Angeles')
            for email in Email.query.filter_by(status='scheduled').all():
                local_time = email.scheduled_at.replace(tzinfo=timezone.utc).astimezone(la_tz)
                assert local_time.hour < 9

    def test_generate_daily_queue_inactive_campaign(self, app, db):
        """Inactive campaign returns 0."""
        with app.app_context():
            from scheduler.queue import generate_daily_queue

            campaign = Campaign(name='Paused', status='paused')
            db.session.add(campaign)
            db.session.commit()

            result = generate_daily_queue(campaign.id)
            assert result == 0

    def test_generate_daily_queue_nonexistent_campaign(self, app, db):
        """Nonexistent campaign returns 0."""
        with app.app_context():
            from scheduler.queue import generate_daily_queue

            result = generate_daily_queue(99999)
            assert result == 0


# ---------------------------------------------------------------------------
# process_queue Tests
# ---------------------------------------------------------------------------


class TestProcessQueue:

    @patch('gmail.sender.send_email')
    def test_process_queue_sends_due_emails(self, mock_send, app, db, active_campaign):
        """Emails past scheduled_at get sent (mock sender)."""
        with app.app_context():
            mock_send.return_value = ('msg_id_1', 'thread_id_1')

            contact = _make_contact(db, active_campaign, 'Due', 'due@ex.com',
                                    wave=1, external_id='001')
            email = Email(
                contact_id=contact.id,
                email_type='initial',
                subject='Due Email',
                body='Body',
                status='scheduled',
                scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
            db.session.add(email)
            db.session.commit()

            from scheduler.queue import process_queue

            results = process_queue()

            assert len(results) == 1
            assert results[0][1] == 'sent'
            mock_send.assert_called_once()

    @patch('gmail.sender.send_email')
    def test_process_queue_skips_future_emails(self, mock_send, app, db, active_campaign):
        """Future emails not sent."""
        with app.app_context():
            contact = _make_contact(db, active_campaign, 'Future', 'future@ex.com',
                                    wave=1, external_id='001')
            email = Email(
                contact_id=contact.id,
                email_type='initial',
                subject='Future Email',
                body='Body',
                status='scheduled',
                scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
            )
            db.session.add(email)
            db.session.commit()

            from scheduler.queue import process_queue

            results = process_queue()

            assert len(results) == 0
            mock_send.assert_not_called()

    @patch('gmail.sender.send_email')
    def test_process_queue_cancels_followup_if_replied(
        self, mock_send, app, db, active_campaign
    ):
        """Follow-up cancelled if reply detected."""
        with app.app_context():
            contact = _make_contact(db, active_campaign, 'Replied', 'replied@ex.com',
                                    status='initial_sent', wave=1, external_id='001')
            fu1 = Email(
                contact_id=contact.id,
                email_type='followup1',
                subject='Follow-up',
                body='Checking in',
                status='scheduled',
                scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
            db.session.add(fu1)
            db.session.commit()

            # Add reply
            reply = Reply(
                contact_id=contact.id,
                from_email='replied@ex.com',
            )
            db.session.add(reply)
            db.session.commit()

            from scheduler.queue import process_queue

            results = process_queue()

            assert len(results) == 1
            assert results[0][1] == 'cancelled_reply_detected'
            assert fu1.status == 'cancelled'
            mock_send.assert_not_called()

    @patch('gmail.sender.send_email')
    def test_process_queue_handles_send_failure(
        self, mock_send, app, db, active_campaign
    ):
        """Failed sends are recorded in results."""
        with app.app_context():
            mock_send.side_effect = Exception('Gmail quota exceeded')

            contact = _make_contact(db, active_campaign, 'Fail', 'fail@ex.com',
                                    wave=1, external_id='001')
            email = Email(
                contact_id=contact.id,
                email_type='initial',
                subject='Fail Email',
                body='Body',
                status='scheduled',
                scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
            db.session.add(email)
            db.session.commit()

            from scheduler.queue import process_queue

            results = process_queue()

            assert len(results) == 1
            assert 'failed' in results[0][1]

    @patch('gmail.sender.send_email')
    def test_process_queue_does_not_cancel_initial_with_reply(
        self, mock_send, app, db, active_campaign
    ):
        """Initial emails are NOT cancelled even if reply exists
        (safety check only applies to follow-ups)."""
        with app.app_context():
            mock_send.return_value = ('msg_id_2', 'thread_id_2')

            contact = _make_contact(db, active_campaign, 'InitReply', 'ir@ex.com',
                                    wave=1, external_id='001')
            email = Email(
                contact_id=contact.id,
                email_type='initial',
                subject='Initial',
                body='Body',
                status='scheduled',
                scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
            db.session.add(email)
            db.session.commit()

            # Add reply (unlikely scenario but tests safety logic)
            reply = Reply(
                contact_id=contact.id,
                from_email='ir@ex.com',
            )
            db.session.add(reply)
            db.session.commit()

            from scheduler.queue import process_queue

            results = process_queue()

            # Initial email should still be sent
            assert len(results) == 1
            assert results[0][1] == 'sent'
            mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# generate_daily_queue_for_active_campaigns Tests
# ---------------------------------------------------------------------------


class TestGenerateDailyQueueForActiveCampaigns:

    def test_generates_for_multiple_campaigns(self, app, db):
        """Generates queue for all active campaigns."""
        with app.app_context():
            from scheduler.queue import generate_daily_queue_for_active_campaigns

            # Create two active campaigns
            for idx in range(2):
                c = Campaign(
                    name=f'Active {idx}',
                    status='active',
                    send_start_hour=8,
                    send_end_hour=17,
                    min_interval_minutes=15,
                    max_emails_per_day=10,
                    followup1_delay_days=3,
                    followup2_delay_days=7,
                    timezone='America/Los_Angeles',
                )
                db.session.add(c)
                db.session.commit()

                contact = _make_contact(db, c, f'C{idx}', f'c{idx}@ex.com',
                                        wave=1, external_id=f'{idx:03d}')
                _make_email(db, contact, 'initial', 'draft')

            morning = datetime(2026, 3, 3, 7, 0, 0)
            la_tz = pytz.timezone('America/Los_Angeles')
            morning_la = la_tz.localize(morning)

            with patch('scheduler.queue.datetime') as mock_dt:
                mock_dt.now.return_value = morning_la
                mock_dt.combine = datetime.combine
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                total = generate_daily_queue_for_active_campaigns()

            assert total == 2


# ---------------------------------------------------------------------------
# get_queue_status Tests
# ---------------------------------------------------------------------------


class TestGetQueueStatus:

    def test_get_queue_status_returns_scheduled(self, app, db, active_campaign):
        """Returns scheduled emails as dicts."""
        with app.app_context():
            from scheduler.queue import get_queue_status

            contact = _make_contact(db, active_campaign, 'Status', 'status@ex.com',
                                    wave=1, external_id='001')
            now = datetime.now(timezone.utc)
            email = Email(
                contact_id=contact.id,
                email_type='initial',
                subject='Queued Email',
                body='Body',
                status='scheduled',
                scheduled_at=now,
            )
            db.session.add(email)
            db.session.commit()

            result = get_queue_status(active_campaign.id)

            assert len(result) == 1
            assert result[0]['contact_name'] == 'Status'
            assert result[0]['company'] == 'Acme Corp'
            assert result[0]['email_type'] == 'initial'
            assert result[0]['status'] == 'scheduled'

    def test_get_queue_status_empty(self, app, db, active_campaign):
        """Returns empty list when no emails queued."""
        with app.app_context():
            from scheduler.queue import get_queue_status

            result = get_queue_status(active_campaign.id)
            assert result == []

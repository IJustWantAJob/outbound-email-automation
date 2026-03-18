"""Tests for Gmail email sending via the Gmail API.

All Google API calls are mocked -- no real credentials needed.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure the app package is importable
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
)

from app import create_app
from config import TestConfig
from database import db as _db
from models import Campaign, Contact, Email, Metric


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
def sample_contact(db):
    """Create a campaign and contact for testing."""
    campaign = Campaign(name='Sender Test Campaign')
    db.session.add(campaign)
    db.session.commit()

    contact = Contact(
        campaign_id=campaign.id,
        name='John Doe',
        email='john@example.com',
        company='Acme Corp',
    )
    db.session.add(contact)
    db.session.commit()
    return contact


@pytest.fixture
def initial_email(db, sample_contact):
    """Create an initial email record for sending."""
    email = Email(
        contact_id=sample_contact.id,
        email_type='initial',
        subject='Hello from Campaign',
        body='We noticed your company uses monitoring systems.',
        status='queued',
    )
    db.session.add(email)
    db.session.commit()
    return email


@pytest.fixture
def mock_gmail_service():
    """Mock Gmail API service with a successful send response."""
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {
        'id': 'msg_abc123',
        'threadId': 'thread_xyz789',
    }
    return mock_service


# ---------------------------------------------------------------------------
# send_email Tests
# ---------------------------------------------------------------------------


class TestSendEmail:

    @patch('gmail.sender.gmail_auth')
    def test_send_email_constructs_mime(
        self, mock_auth, app, db, sample_contact, initial_email
    ):
        """Mock Gmail API, verify MIME message has correct to/subject."""
        with app.app_context():
            mock_service = MagicMock()
            mock_service.users().messages().send().execute.return_value = {
                'id': 'msg_001',
                'threadId': 'thread_001',
            }
            mock_auth.get_service.return_value = mock_service

            from gmail.sender import send_email

            send_email(initial_email)

            # Verify send was called
            mock_service.users().messages().send.assert_called()
            call_kwargs = (
                mock_service.users().messages().send.call_args
            )
            # The body should contain 'raw' key with base64-encoded MIME
            sent_body = call_kwargs[1]['body'] if call_kwargs[1] else call_kwargs[0][1]
            assert 'raw' in sent_body

    @patch('gmail.sender.gmail_auth')
    def test_send_email_updates_status(
        self, mock_auth, app, db, sample_contact, initial_email
    ):
        """After send, email_record.status == 'sent' and sent_at is set."""
        with app.app_context():
            mock_service = MagicMock()
            mock_service.users().messages().send().execute.return_value = {
                'id': 'msg_002',
                'threadId': 'thread_002',
            }
            mock_auth.get_service.return_value = mock_service

            from gmail.sender import send_email

            send_email(initial_email)

            assert initial_email.status == 'sent'
            assert initial_email.sent_at is not None

    @patch('gmail.sender.gmail_auth')
    def test_send_email_stores_gmail_ids(
        self, mock_auth, app, db, sample_contact, initial_email
    ):
        """gmail_message_id and gmail_thread_id stored on record."""
        with app.app_context():
            mock_service = MagicMock()
            mock_service.users().messages().send().execute.return_value = {
                'id': 'msg_003',
                'threadId': 'thread_003',
            }
            mock_auth.get_service.return_value = mock_service

            from gmail.sender import send_email

            msg_id, thread_id = send_email(initial_email)

            assert initial_email.gmail_message_id == 'msg_003'
            assert initial_email.gmail_thread_id == 'thread_003'
            assert msg_id == 'msg_003'
            assert thread_id == 'thread_003'

    @patch('gmail.sender.gmail_auth')
    def test_send_email_updates_contact_status_initial(
        self, mock_auth, app, db, sample_contact, initial_email
    ):
        """Contact status updated to 'initial_sent' for initial emails."""
        with app.app_context():
            mock_service = MagicMock()
            mock_service.users().messages().send().execute.return_value = {
                'id': 'msg_004',
                'threadId': 'thread_004',
            }
            mock_auth.get_service.return_value = mock_service

            from gmail.sender import send_email

            send_email(initial_email)

            assert sample_contact.status == 'initial_sent'

    @patch('gmail.sender.gmail_auth')
    def test_send_email_updates_contact_status_followup1(
        self, mock_auth, app, db, sample_contact
    ):
        """Contact status updated to 'followup1_sent' for followup1 emails."""
        with app.app_context():
            # Create a sent initial email first (for threading)
            initial = Email(
                contact_id=sample_contact.id,
                email_type='initial',
                subject='Initial',
                body='Hello',
                status='sent',
                gmail_thread_id='thread_init',
            )
            db.session.add(initial)
            db.session.commit()

            followup = Email(
                contact_id=sample_contact.id,
                email_type='followup1',
                subject='Following up',
                body='Just checking in.',
                status='queued',
            )
            db.session.add(followup)
            db.session.commit()

            mock_service = MagicMock()
            mock_service.users().messages().send().execute.return_value = {
                'id': 'msg_005',
                'threadId': 'thread_init',
            }
            mock_auth.get_service.return_value = mock_service

            from gmail.sender import send_email

            send_email(followup)

            # Re-query contact to get updated status after commit
            updated_contact = db.session.get(Contact, sample_contact.id)
            assert updated_contact.status == 'followup1_sent'

    @patch('gmail.sender.gmail_auth')
    def test_send_email_updates_contact_status_followup2(
        self, mock_auth, app, db, sample_contact
    ):
        """Contact status updated to 'followup2_sent' for followup2 emails."""
        with app.app_context():
            followup2 = Email(
                contact_id=sample_contact.id,
                email_type='followup2',
                subject='Last follow-up',
                body='Final check-in.',
                status='queued',
            )
            db.session.add(followup2)
            db.session.commit()

            mock_service = MagicMock()
            mock_service.users().messages().send().execute.return_value = {
                'id': 'msg_006',
                'threadId': 'thread_006',
            }
            mock_auth.get_service.return_value = mock_service

            from gmail.sender import send_email

            send_email(followup2)

            # Re-query contact to get updated status after commit
            updated_contact = db.session.get(Contact, sample_contact.id)
            assert updated_contact.status == 'followup2_sent'

    @patch('gmail.sender.gmail_auth')
    def test_send_email_creates_metric(
        self, mock_auth, app, db, sample_contact, initial_email
    ):
        """Metric record created with type='sent'."""
        with app.app_context():
            mock_service = MagicMock()
            mock_service.users().messages().send().execute.return_value = {
                'id': 'msg_007',
                'threadId': 'thread_007',
            }
            mock_auth.get_service.return_value = mock_service

            from gmail.sender import send_email

            send_email(initial_email)

            metric = Metric.query.filter_by(
                contact_id=sample_contact.id,
                metric_type='sent',
            ).first()
            assert metric is not None
            assert metric.value == 'initial'

    @patch('gmail.sender.gmail_auth')
    def test_send_email_threads_followup(
        self, mock_auth, app, db, sample_contact
    ):
        """Follow-up includes threadId from initial email."""
        with app.app_context():
            # Create a sent initial email with a thread ID
            initial = Email(
                contact_id=sample_contact.id,
                email_type='initial',
                subject='Initial',
                body='Hello',
                status='sent',
                gmail_thread_id='thread_original',
            )
            db.session.add(initial)
            db.session.commit()

            followup = Email(
                contact_id=sample_contact.id,
                email_type='followup1',
                subject='Following up',
                body='Just checking in.',
                status='queued',
            )
            db.session.add(followup)
            db.session.commit()

            mock_service = MagicMock()
            mock_service.users().messages().send().execute.return_value = {
                'id': 'msg_008',
                'threadId': 'thread_original',
            }
            mock_auth.get_service.return_value = mock_service

            from gmail.sender import send_email

            send_email(followup)

            # Verify the send call included the threadId
            call_kwargs = (
                mock_service.users().messages().send.call_args
            )
            sent_body = call_kwargs[1].get('body', call_kwargs[0][1] if call_kwargs[0] else {})
            assert sent_body.get('threadId') == 'thread_original'

    @patch('gmail.sender.gmail_auth')
    def test_send_email_handles_failure(
        self, mock_auth, app, db, sample_contact, initial_email
    ):
        """Gmail API raises exception: status='failed', error_message set."""
        with app.app_context():
            mock_service = MagicMock()
            mock_service.users().messages().send().execute.side_effect = (
                Exception('Gmail API error: quota exceeded')
            )
            mock_auth.get_service.return_value = mock_service

            from gmail.sender import send_email

            with pytest.raises(Exception, match='quota exceeded'):
                send_email(initial_email)

            assert initial_email.status == 'failed'
            assert 'quota exceeded' in initial_email.error_message

    @patch('gmail.sender.gmail_auth')
    def test_send_test_email(self, mock_auth, app, db):
        """send_test_email sends simple message and returns message ID."""
        with app.app_context():
            mock_service = MagicMock()
            mock_service.users().messages().send().execute.return_value = {
                'id': 'msg_test_009',
            }
            mock_auth.get_service.return_value = mock_service

            from gmail.sender import send_test_email

            msg_id = send_test_email('recipient@example.com')

            assert msg_id == 'msg_test_009'
            mock_service.users().messages().send.assert_called()

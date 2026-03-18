"""Tests for Gmail reply detection via thread scanning.

All Google API calls are mocked -- no real credentials needed.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Ensure the app package is importable
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
)

from app import create_app
from config import TestConfig
from database import db as _db
from models import Campaign, Contact, Email, Metric, Reply


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
def sample_data(db):
    """Create a campaign, contact, and sent email with a thread ID."""
    campaign = Campaign(name='Reader Test Campaign')
    db.session.add(campaign)
    db.session.commit()

    contact = Contact(
        campaign_id=campaign.id,
        name='Jane Smith',
        email='jane@example.com',
        company='DataCenter Inc',
        status='initial_sent',
    )
    db.session.add(contact)
    db.session.commit()

    email = Email(
        contact_id=contact.id,
        email_type='initial',
        subject='Hello from Campaign',
        body='We help data centers save energy.',
        status='sent',
        gmail_message_id='msg_sent_001',
        gmail_thread_id='thread_abc',
        sent_at=datetime.now(timezone.utc),
    )
    db.session.add(email)
    db.session.commit()

    return campaign, contact, email


def _make_thread_with_reply(our_email='test@gmail.com'):
    """Build a mock Gmail thread with our message and an external reply."""
    return {
        'id': 'thread_abc',
        'messages': [
            {
                'id': 'msg_sent_001',
                'snippet': 'We help data centers save energy.',
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': our_email},
                        {'name': 'Subject', 'value': 'Hello from Campaign'},
                        {
                            'name': 'Date',
                            'value': 'Mon, 3 Mar 2026 10:00:00 -0800',
                        },
                    ]
                },
            },
            {
                'id': 'msg_reply_002',
                'snippet': 'Thanks for reaching out, we are interested!',
                'payload': {
                    'headers': [
                        {
                            'name': 'From',
                            'value': 'Jane Smith <jane@example.com>',
                        },
                        {
                            'name': 'Subject',
                            'value': 'Re: Hello from Campaign',
                        },
                        {
                            'name': 'Date',
                            'value': 'Mon, 3 Mar 2026 14:30:00 -0800',
                        },
                    ]
                },
            },
        ],
    }


def _make_thread_only_ours(our_email='test@gmail.com'):
    """Build a mock Gmail thread with only our own messages."""
    return {
        'id': 'thread_abc',
        'messages': [
            {
                'id': 'msg_sent_001',
                'snippet': 'We help data centers save energy.',
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': our_email},
                        {'name': 'Subject', 'value': 'Hello from Campaign'},
                    ]
                },
            },
            {
                'id': 'msg_sent_followup',
                'snippet': 'Just following up on my previous email.',
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': our_email},
                        {'name': 'Subject', 'value': 'Re: Hello from Campaign'},
                    ]
                },
            },
        ],
    }


def _make_single_message_thread(our_email='test@gmail.com'):
    """Build a mock Gmail thread with only one message (ours)."""
    return {
        'id': 'thread_abc',
        'messages': [
            {
                'id': 'msg_sent_001',
                'snippet': 'We help data centers save energy.',
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': our_email},
                        {'name': 'Subject', 'value': 'Hello from Campaign'},
                    ]
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# check_for_replies Tests
# ---------------------------------------------------------------------------


class TestCheckForReplies:

    @patch('gmail.reader.gmail_auth')
    def test_check_replies_detects_reply(
        self, mock_auth, app, db, sample_data
    ):
        """Thread has 2 messages, second is external -> Reply created."""
        with app.app_context():
            campaign, contact, email = sample_data

            mock_service = MagicMock()
            mock_service.users().threads().get().execute.return_value = (
                _make_thread_with_reply()
            )
            mock_auth.get_service.return_value = mock_service
            mock_auth.get_connected_email.return_value = 'test@gmail.com'

            from gmail.reader import check_for_replies

            result = check_for_replies()

            assert len(result) == 1
            reply = Reply.query.filter_by(contact_id=contact.id).first()
            assert reply is not None
            assert reply.gmail_message_id == 'msg_reply_002'
            assert reply.gmail_thread_id == 'thread_abc'
            assert reply.from_email == 'jane@example.com'
            assert 'interested' in reply.snippet

    @patch('gmail.reader.gmail_auth')
    def test_check_replies_updates_contact_status(
        self, mock_auth, app, db, sample_data
    ):
        """Contact status updated to 'replied'."""
        with app.app_context():
            campaign, contact, email = sample_data

            mock_service = MagicMock()
            mock_service.users().threads().get().execute.return_value = (
                _make_thread_with_reply()
            )
            mock_auth.get_service.return_value = mock_service
            mock_auth.get_connected_email.return_value = 'test@gmail.com'

            from gmail.reader import check_for_replies

            check_for_replies()

            # Re-query contact to get updated status after commit
            updated_contact = db.session.get(Contact, contact.id)
            assert updated_contact.status == 'replied'

    @patch('gmail.reader.gmail_auth')
    def test_check_replies_cancels_followups(
        self, mock_auth, app, db, sample_data
    ):
        """Scheduled follow-ups are cancelled when a reply is detected."""
        with app.app_context():
            campaign, contact, email = sample_data

            # Add scheduled follow-ups
            fu1 = Email(
                contact_id=contact.id,
                email_type='followup1',
                subject='Follow-up 1',
                body='Checking in.',
                status='scheduled',
            )
            fu2 = Email(
                contact_id=contact.id,
                email_type='followup2',
                subject='Follow-up 2',
                body='Last check-in.',
                status='draft',
            )
            db.session.add_all([fu1, fu2])
            db.session.commit()

            mock_service = MagicMock()
            mock_service.users().threads().get().execute.return_value = (
                _make_thread_with_reply()
            )
            mock_auth.get_service.return_value = mock_service
            mock_auth.get_connected_email.return_value = 'test@gmail.com'

            from gmail.reader import check_for_replies

            check_for_replies()

            db.session.refresh(fu1)
            db.session.refresh(fu2)
            assert fu1.status == 'cancelled'
            assert fu2.status == 'cancelled'

    @patch('gmail.reader.gmail_auth')
    def test_check_replies_ignores_own_messages(
        self, mock_auth, app, db, sample_data
    ):
        """Thread with only our messages -> no reply created."""
        with app.app_context():
            campaign, contact, email = sample_data

            mock_service = MagicMock()
            mock_service.users().threads().get().execute.return_value = (
                _make_thread_only_ours()
            )
            mock_auth.get_service.return_value = mock_service
            mock_auth.get_connected_email.return_value = 'test@gmail.com'

            from gmail.reader import check_for_replies

            result = check_for_replies()

            assert len(result) == 0
            assert Reply.query.count() == 0

    @patch('gmail.reader.gmail_auth')
    def test_check_replies_skips_existing_replies(
        self, mock_auth, app, db, sample_data
    ):
        """Already detected reply -> skipped (no duplicate)."""
        with app.app_context():
            campaign, contact, email = sample_data

            # Pre-create a reply for this thread
            existing_reply = Reply(
                contact_id=contact.id,
                gmail_message_id='msg_reply_existing',
                gmail_thread_id='thread_abc',
                from_email='jane@example.com',
                subject='Re: Hello',
                snippet='Already detected',
            )
            db.session.add(existing_reply)
            db.session.commit()

            mock_service = MagicMock()
            mock_service.users().threads().get().execute.return_value = (
                _make_thread_with_reply()
            )
            mock_auth.get_service.return_value = mock_service
            mock_auth.get_connected_email.return_value = 'test@gmail.com'

            from gmail.reader import check_for_replies

            result = check_for_replies()

            assert len(result) == 0
            # Should still only have the one pre-existing reply
            assert Reply.query.count() == 1

    @patch('gmail.reader.gmail_auth')
    def test_check_replies_handles_empty_threads(
        self, mock_auth, app, db, sample_data
    ):
        """Thread with 1 message -> no reply created."""
        with app.app_context():
            campaign, contact, email = sample_data

            mock_service = MagicMock()
            mock_service.users().threads().get().execute.return_value = (
                _make_single_message_thread()
            )
            mock_auth.get_service.return_value = mock_service
            mock_auth.get_connected_email.return_value = 'test@gmail.com'

            from gmail.reader import check_for_replies

            result = check_for_replies()

            assert len(result) == 0
            assert Reply.query.count() == 0

    @patch('gmail.reader.gmail_auth')
    def test_check_replies_extracts_email(
        self, mock_auth, app, db, sample_data
    ):
        """'John <john@example.com>' -> from_email is 'john@example.com'."""
        with app.app_context():
            campaign, contact, email = sample_data

            mock_service = MagicMock()
            mock_service.users().threads().get().execute.return_value = (
                _make_thread_with_reply()
            )
            mock_auth.get_service.return_value = mock_service
            mock_auth.get_connected_email.return_value = 'test@gmail.com'

            from gmail.reader import check_for_replies

            check_for_replies()

            reply = Reply.query.filter_by(contact_id=contact.id).first()
            assert reply is not None
            # The reply from_email should be extracted from
            # "Jane Smith <jane@example.com>"
            assert reply.from_email == 'jane@example.com'

    @patch('gmail.reader.gmail_auth')
    def test_check_replies_creates_metric(
        self, mock_auth, app, db, sample_data
    ):
        """Metric with type='replied' created."""
        with app.app_context():
            campaign, contact, email = sample_data

            mock_service = MagicMock()
            mock_service.users().threads().get().execute.return_value = (
                _make_thread_with_reply()
            )
            mock_auth.get_service.return_value = mock_service
            mock_auth.get_connected_email.return_value = 'test@gmail.com'

            from gmail.reader import check_for_replies

            check_for_replies()

            metric = Metric.query.filter_by(
                contact_id=contact.id,
                metric_type='replied',
            ).first()
            assert metric is not None
            assert 'interested' in metric.value

    @patch('gmail.reader.gmail_auth')
    def test_check_replies_returns_new_replies(
        self, mock_auth, app, db, sample_data
    ):
        """Returns list of (contact_id, snippet) tuples."""
        with app.app_context():
            campaign, contact, email = sample_data

            mock_service = MagicMock()
            mock_service.users().threads().get().execute.return_value = (
                _make_thread_with_reply()
            )
            mock_auth.get_service.return_value = mock_service
            mock_auth.get_connected_email.return_value = 'test@gmail.com'

            from gmail.reader import check_for_replies

            result = check_for_replies()

            assert len(result) == 1
            contact_id, snippet = result[0]
            assert contact_id == contact.id
            assert 'interested' in snippet


# ---------------------------------------------------------------------------
# _extract_email Tests
# ---------------------------------------------------------------------------


class TestExtractEmail:

    def test_extract_email_angle_brackets(self):
        """Extract email from 'Name <email@example.com>' format."""
        from gmail.reader import _extract_email

        assert _extract_email('John Doe <john@example.com>') == 'john@example.com'

    def test_extract_email_plain(self):
        """Extract plain email address."""
        from gmail.reader import _extract_email

        assert _extract_email('john@example.com') == 'john@example.com'

    def test_extract_email_with_quotes(self):
        """Extract email from '"John Doe" <john@example.com>' format."""
        from gmail.reader import _extract_email

        assert (
            _extract_email('"John Doe" <john@example.com>')
            == 'john@example.com'
        )

    def test_extract_email_no_email(self):
        """Return None when no email address found."""
        from gmail.reader import _extract_email

        assert _extract_email('No Email Here') is None

    def test_extract_email_empty_string(self):
        """Return None for empty string."""
        from gmail.reader import _extract_email

        assert _extract_email('') is None

    def test_extract_email_with_spaces(self):
        """Handle email with leading/trailing spaces."""
        from gmail.reader import _extract_email

        assert _extract_email('  user@domain.com  ') == 'user@domain.com'

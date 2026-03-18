"""Comprehensive tests for Gmail OAuth2 authentication and routes.

All Google API calls are mocked -- no real credentials needed.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

# Ensure the app package is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from config import TestConfig
from database import db as _db
from gmail.auth import GmailAuth, GmailNotConnectedError, gmail_auth
from models import GmailToken


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class GmailTestConfig(TestConfig):
    """TestConfig with a real Fernet key for encryption tests."""

    FERNET_KEY = Fernet.generate_key().decode()
    GMAIL_CLIENT_SECRET_PATH = '/tmp/fake_client_secret.json'
    REDIRECT_URI = 'http://localhost:5000/gmail/callback'


class GmailTestConfigNoFernet(TestConfig):
    """TestConfig without a Fernet key (dev/plaintext mode)."""

    FERNET_KEY = ''
    GMAIL_CLIENT_SECRET_PATH = '/tmp/fake_client_secret.json'
    REDIRECT_URI = 'http://localhost:5000/gmail/callback'


@pytest.fixture
def app_with_fernet():
    """Create a Flask app with Fernet encryption enabled."""
    app = create_app(GmailTestConfig)
    yield app


@pytest.fixture
def app_no_fernet():
    """Create a Flask app without Fernet encryption (plaintext mode)."""
    app = create_app(GmailTestConfigNoFernet)
    yield app


@pytest.fixture
def db_fernet(app_with_fernet):
    """Database fixture with Fernet-enabled app."""
    with app_with_fernet.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def db_no_fernet(app_no_fernet):
    """Database fixture without Fernet encryption."""
    with app_no_fernet.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def client_fernet(app_with_fernet):
    """Test client with Fernet-enabled app."""
    return app_with_fernet.test_client()


@pytest.fixture
def auth_with_fernet(app_with_fernet):
    """GmailAuth instance initialized with Fernet key."""
    auth = GmailAuth()
    auth.init_app(app_with_fernet)
    return auth


@pytest.fixture
def auth_no_fernet(app_no_fernet):
    """GmailAuth instance without Fernet key."""
    auth = GmailAuth()
    auth.init_app(app_no_fernet)
    return auth


def _make_token_data():
    """Helper: create a sample token data dict."""
    return {
        'token': 'ya29.access-token-abc',
        'refresh_token': '1//refresh-token-xyz',
        'token_uri': 'https://oauth2.googleapis.com/token',
        'client_id': 'client-id-123.apps.googleusercontent.com',
        'client_secret': 'client-secret-456',
        'scopes': [
            'https://www.googleapis.com/auth/gmail.send',
            'https://www.googleapis.com/auth/gmail.readonly',
        ],
    }


def _store_token(db, auth, email='test@gmail.com', is_active=True):
    """Helper: store a GmailToken in the database."""
    token_data = _make_token_data()
    encrypted = auth._encrypt_token(json.dumps(token_data))
    token = GmailToken(
        email_address=email,
        token_json=encrypted,
        is_active=is_active,
    )
    db.session.add(token)
    db.session.commit()
    return token


# ---------------------------------------------------------------------------
# Encryption / Decryption Tests
# ---------------------------------------------------------------------------


class TestEncryptDecrypt:
    """Tests for Fernet encryption and decryption of token data."""

    def test_encrypt_decrypt_roundtrip(self, app_with_fernet, auth_with_fernet):
        """Encrypt then decrypt token JSON, verify identical."""
        with app_with_fernet.app_context():
            original = json.dumps(_make_token_data())
            encrypted = auth_with_fernet._encrypt_token(original)
            # Encrypted string should differ from original
            assert encrypted != original
            decrypted = auth_with_fernet._decrypt_token(encrypted)
            assert decrypted == original
            assert json.loads(decrypted) == _make_token_data()

    def test_encrypt_without_fernet(self, app_no_fernet, auth_no_fernet):
        """No FERNET_KEY means token stored as plaintext (dev mode)."""
        with app_no_fernet.app_context():
            original = json.dumps(_make_token_data())
            encrypted = auth_no_fernet._encrypt_token(original)
            # Should be identical to original (no encryption)
            assert encrypted == original
            decrypted = auth_no_fernet._decrypt_token(encrypted)
            assert decrypted == original


# ---------------------------------------------------------------------------
# Auth URL Generation Tests
# ---------------------------------------------------------------------------


class TestGetAuthUrl:
    """Tests for OAuth2 authorization URL generation."""

    @patch('gmail.auth.Flow.from_client_secrets_file')
    def test_get_auth_url_generates_url(
        self, mock_flow_cls, app_with_fernet, auth_with_fernet
    ):
        """get_auth_url returns a URL containing Google's OAuth endpoint."""
        with app_with_fernet.app_context():
            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                'https://accounts.google.com/o/oauth2/v2/auth?client_id=abc',
                'state-123',
            )
            mock_flow_cls.return_value = mock_flow

            auth_url, state = auth_with_fernet.get_auth_url(state='state-123')

            assert 'google.com/o/oauth2' in auth_url
            assert state == 'state-123'
            mock_flow_cls.assert_called_once()

    @patch('gmail.auth.Flow.from_client_secrets_file')
    def test_get_auth_url_includes_state(
        self, mock_flow_cls, app_with_fernet, auth_with_fernet
    ):
        """Verify the state parameter is passed through to authorization_url."""
        with app_with_fernet.app_context():
            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                'https://accounts.google.com/o/oauth2/v2/auth?state=my-state',
                'my-state',
            )
            mock_flow_cls.return_value = mock_flow

            auth_url, state = auth_with_fernet.get_auth_url(state='my-state')

            mock_flow.authorization_url.assert_called_once_with(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent',
                state='my-state',
            )
            assert state == 'my-state'


# ---------------------------------------------------------------------------
# Handle Callback Tests
# ---------------------------------------------------------------------------


class TestHandleCallback:
    """Tests for the OAuth2 callback handler."""

    @patch('gmail.auth.build')
    @patch('gmail.auth.Flow.from_client_secrets_file')
    def test_handle_callback_stores_token(
        self, mock_flow_cls, mock_build, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """handle_callback creates a GmailToken record in the database."""
        with app_with_fernet.app_context():
            # Mock the OAuth flow
            mock_flow = MagicMock()
            mock_creds = MagicMock()
            mock_creds.token = 'access-token'
            mock_creds.refresh_token = 'refresh-token'
            mock_creds.token_uri = 'https://oauth2.googleapis.com/token'
            mock_creds.client_id = 'client-id'
            mock_creds.client_secret = 'client-secret'
            mock_creds.scopes = {'https://www.googleapis.com/auth/gmail.send'}
            mock_flow.credentials = mock_creds
            mock_flow_cls.return_value = mock_flow

            # Mock Gmail API service
            mock_service = MagicMock()
            mock_service.users().getProfile().execute.return_value = {
                'emailAddress': 'user@gmail.com'
            }
            mock_build.return_value = mock_service

            email = auth_with_fernet.handle_callback(
                'http://localhost:5000/gmail/callback?code=auth-code-123'
            )

            assert email == 'user@gmail.com'
            token = GmailToken.query.filter_by(email_address='user@gmail.com').first()
            assert token is not None
            assert token.is_active is True
            # Verify the stored token can be decrypted
            decrypted = json.loads(
                auth_with_fernet._decrypt_token(token.token_json)
            )
            assert decrypted['token'] == 'access-token'
            assert decrypted['refresh_token'] == 'refresh-token'

    @patch('gmail.auth.build')
    @patch('gmail.auth.Flow.from_client_secrets_file')
    def test_handle_callback_deactivates_old_tokens(
        self, mock_flow_cls, mock_build, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """When a new token is stored, all previous tokens are deactivated."""
        with app_with_fernet.app_context():
            # Create an existing active token
            _store_token(db_fernet, auth_with_fernet, email='old@gmail.com')
            old_token = GmailToken.query.filter_by(
                email_address='old@gmail.com'
            ).first()
            assert old_token.is_active is True

            # Mock the OAuth flow for a new account
            mock_flow = MagicMock()
            mock_creds = MagicMock()
            mock_creds.token = 'new-access-token'
            mock_creds.refresh_token = 'new-refresh-token'
            mock_creds.token_uri = 'https://oauth2.googleapis.com/token'
            mock_creds.client_id = 'client-id'
            mock_creds.client_secret = 'client-secret'
            mock_creds.scopes = {'https://www.googleapis.com/auth/gmail.send'}
            mock_flow.credentials = mock_creds
            mock_flow_cls.return_value = mock_flow

            mock_service = MagicMock()
            mock_service.users().getProfile().execute.return_value = {
                'emailAddress': 'new@gmail.com'
            }
            mock_build.return_value = mock_service

            email = auth_with_fernet.handle_callback(
                'http://localhost:5000/gmail/callback?code=new-code'
            )

            assert email == 'new@gmail.com'

            # Old token should be deactivated
            db_fernet.session.refresh(old_token)
            assert old_token.is_active is False

            # New token should be active
            new_token = GmailToken.query.filter_by(
                email_address='new@gmail.com'
            ).first()
            assert new_token is not None
            assert new_token.is_active is True


# ---------------------------------------------------------------------------
# Get Credentials Tests
# ---------------------------------------------------------------------------


class TestGetCredentials:
    """Tests for credential retrieval and refresh."""

    def test_get_credentials_returns_valid(
        self, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """get_credentials returns a Credentials object when token exists."""
        with app_with_fernet.app_context():
            _store_token(db_fernet, auth_with_fernet)

            with patch.object(
                auth_with_fernet, 'get_credentials'
            ) as mock_get:
                mock_creds = MagicMock()
                mock_creds.token = 'ya29.access-token-abc'
                mock_creds.expired = False
                mock_get.return_value = mock_creds

                creds = auth_with_fernet.get_credentials()
                assert creds.token == 'ya29.access-token-abc'

    def test_get_credentials_raises_not_connected(
        self, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """get_credentials raises GmailNotConnectedError when no token."""
        with app_with_fernet.app_context():
            with pytest.raises(GmailNotConnectedError):
                auth_with_fernet.get_credentials()

    @patch('gmail.auth.Request')
    def test_get_credentials_refreshes_expired(
        self, mock_request_cls, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """get_credentials refreshes an expired token."""
        with app_with_fernet.app_context():
            _store_token(db_fernet, auth_with_fernet)

            with patch('gmail.auth.Credentials') as mock_creds_cls:
                mock_creds = MagicMock()
                mock_creds.expired = True
                mock_creds.refresh_token = 'refresh-token'
                mock_creds.token = 'new-access-token'
                mock_creds_cls.return_value = mock_creds

                creds = auth_with_fernet.get_credentials()

                mock_creds.refresh.assert_called_once()
                assert creds.token == 'new-access-token'

                # Verify the token was updated in the database
                token_record = GmailToken.query.filter_by(
                    is_active=True
                ).first()
                stored = json.loads(
                    auth_with_fernet._decrypt_token(token_record.token_json)
                )
                assert stored['token'] == 'new-access-token'


# ---------------------------------------------------------------------------
# Connection Status Tests
# ---------------------------------------------------------------------------


class TestConnectionStatus:
    """Tests for is_connected, get_connected_email, and disconnect."""

    def test_disconnect_deactivates_token(
        self, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """disconnect() sets is_active=False on all tokens."""
        with app_with_fernet.app_context():
            _store_token(db_fernet, auth_with_fernet)
            assert auth_with_fernet.is_connected() is True

            auth_with_fernet.disconnect()

            token = GmailToken.query.first()
            assert token.is_active is False
            assert auth_with_fernet.is_connected() is False

    def test_is_connected_true_when_token_exists(
        self, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """is_connected() returns True when an active token exists."""
        with app_with_fernet.app_context():
            _store_token(db_fernet, auth_with_fernet)
            assert auth_with_fernet.is_connected() is True

    def test_is_connected_false_when_no_token(
        self, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """is_connected() returns False when no active token exists."""
        with app_with_fernet.app_context():
            assert auth_with_fernet.is_connected() is False

    def test_get_connected_email(
        self, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """get_connected_email() returns the email when connected."""
        with app_with_fernet.app_context():
            _store_token(db_fernet, auth_with_fernet, email='connected@gmail.com')
            assert auth_with_fernet.get_connected_email() == 'connected@gmail.com'

    def test_get_connected_email_none_when_disconnected(
        self, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """get_connected_email() returns None when not connected."""
        with app_with_fernet.app_context():
            assert auth_with_fernet.get_connected_email() is None


# ---------------------------------------------------------------------------
# Route Tests
# ---------------------------------------------------------------------------


class TestConnectRoute:
    """Tests for the /gmail/connect route."""

    @patch('gmail.auth.Flow.from_client_secrets_file')
    def test_connect_route_redirects(self, mock_flow_cls, app_with_fernet):
        """GET /gmail/connect returns a redirect to Google OAuth."""
        with app_with_fernet.app_context():
            # Re-init gmail_auth for this app context
            gmail_auth.init_app(app_with_fernet)

            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                'https://accounts.google.com/o/oauth2/v2/auth?client_id=abc',
                'state-xyz',
            )
            mock_flow_cls.return_value = mock_flow

            client = app_with_fernet.test_client()
            response = client.get('/gmail/connect')

            assert response.status_code == 302
            assert 'google.com/o/oauth2' in response.headers['Location']


class TestCallbackRoute:
    """Tests for the /gmail/callback route."""

    def test_callback_validates_state(self, app_with_fernet):
        """Callback with wrong state returns 403."""
        with app_with_fernet.app_context():
            gmail_auth.init_app(app_with_fernet)

            client = app_with_fernet.test_client()
            # Set a state in the session
            with client.session_transaction() as sess:
                sess['oauth_state'] = 'correct-state'

            response = client.get(
                '/gmail/callback?state=wrong-state&code=some-code'
            )
            assert response.status_code == 403
            data = response.get_json()
            assert 'Invalid state' in data['error']

    def test_callback_rejects_missing_state(self, app_with_fernet):
        """Callback with no state in session returns 403."""
        with app_with_fernet.app_context():
            gmail_auth.init_app(app_with_fernet)

            client = app_with_fernet.test_client()
            # No state set in session
            response = client.get('/gmail/callback?state=some-state&code=abc')
            assert response.status_code == 403
            data = response.get_json()
            assert 'Invalid state' in data['error']

    def test_callback_handles_oauth_error(self, app_with_fernet):
        """Callback with error query param returns 400."""
        with app_with_fernet.app_context():
            gmail_auth.init_app(app_with_fernet)

            client = app_with_fernet.test_client()
            with client.session_transaction() as sess:
                sess['oauth_state'] = 'valid-state'

            response = client.get(
                '/gmail/callback?state=valid-state&error=access_denied'
            )
            assert response.status_code == 400
            data = response.get_json()
            assert 'access_denied' in data['error']


class TestStatusRoute:
    """Tests for the /gmail/status route."""

    def test_status_returns_json_disconnected(self, app_with_fernet, db_fernet):
        """GET /gmail/status returns connected=False when no token."""
        with app_with_fernet.app_context():
            gmail_auth.init_app(app_with_fernet)

            client = app_with_fernet.test_client()
            response = client.get('/gmail/status')

            assert response.status_code == 200
            data = response.get_json()
            assert data['connected'] is False
            assert data['email'] is None

    def test_status_returns_json_connected(
        self, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """GET /gmail/status returns connected=True with email when token exists."""
        with app_with_fernet.app_context():
            gmail_auth.init_app(app_with_fernet)
            _store_token(db_fernet, auth_with_fernet, email='user@gmail.com')

            client = app_with_fernet.test_client()
            response = client.get('/gmail/status')

            assert response.status_code == 200
            data = response.get_json()
            assert data['connected'] is True
            assert data['email'] == 'user@gmail.com'


class TestDisconnectRoute:
    """Tests for the /gmail/disconnect route."""

    def test_disconnect_route(
        self, app_with_fernet, db_fernet, auth_with_fernet
    ):
        """POST /gmail/disconnect deactivates tokens and returns JSON."""
        with app_with_fernet.app_context():
            gmail_auth.init_app(app_with_fernet)
            _store_token(db_fernet, auth_with_fernet)

            client = app_with_fernet.test_client()
            response = client.post('/gmail/disconnect')

            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'disconnected'

            # Verify token is deactivated
            token = GmailToken.query.first()
            assert token.is_active is False

"""Gmail OAuth2 authentication and token management.

Handles the OAuth2 flow for Gmail API access, including token
encryption/decryption with Fernet and token refresh logic.
"""

import json
import os

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build


class GmailNotConnectedError(Exception):
    """Raised when Gmail is not connected but an operation requires it."""

    pass


class GmailAuth:
    """Manages Gmail OAuth2 authentication and encrypted token storage.

    Supports the Flask app-factory pattern via init_app().
    """

    def __init__(self, app=None):
        self.app = app
        self.fernet = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with a Flask app, setting up Fernet encryption."""
        self.app = app
        fernet_key = app.config.get('FERNET_KEY')
        if fernet_key:
            self.fernet = Fernet(
                fernet_key.encode() if isinstance(fernet_key, str) else fernet_key
            )
        else:
            self.fernet = None

    def _encrypt_token(self, token_json_str):
        """Encrypt token JSON string before storing in DB."""
        if self.fernet:
            return self.fernet.encrypt(token_json_str.encode()).decode()
        return token_json_str  # No encryption in dev/test

    def _decrypt_token(self, encrypted_str):
        """Decrypt token JSON string from DB."""
        if self.fernet:
            return self.fernet.decrypt(encrypted_str.encode()).decode()
        return encrypted_str

    def _create_flow(self):
        """Create an OAuth2 Flow instance.

        Tries to load from client_secret.json first. If the file is missing,
        falls back to constructing the flow from GOOGLE_LOGIN_CLIENT_ID and
        GOOGLE_LOGIN_CLIENT_SECRET env-var-based config (same OAuth client).
        This makes the app resilient to deploys that may delete the JSON file.

        Returns:
            google_auth_oauthlib.flow.Flow instance.
        """
        secret_path = self.app.config.get('GMAIL_CLIENT_SECRET_PATH', '')
        scopes = self.app.config['GMAIL_SCOPES']
        redirect_uri = self.app.config['REDIRECT_URI']

        if secret_path and os.path.exists(secret_path):
            return Flow.from_client_secrets_file(
                secret_path,
                scopes=scopes,
                redirect_uri=redirect_uri,
            )

        # Fallback: build from env-var config (no file needed).
        # Try GMAIL_CLIENT_ID/SECRET first (dedicated Gmail send OAuth client),
        # then fall back to GOOGLE_LOGIN_CLIENT_ID/SECRET (shared client).
        client_id = (
            self.app.config.get('GMAIL_CLIENT_ID')
            or self.app.config.get('GOOGLE_LOGIN_CLIENT_ID', '')
        )
        client_secret = (
            self.app.config.get('GMAIL_CLIENT_SECRET')
            or self.app.config.get('GOOGLE_LOGIN_CLIENT_SECRET', '')
        )

        if not client_id or not client_secret:
            raise FileNotFoundError(
                f'Gmail client_secret.json not found at {secret_path} and '
                'GOOGLE_LOGIN_CLIENT_ID/SECRET not configured. '
                'Upload client_secret.json or set the env vars.'
            )

        client_config = {
            'web': {
                'client_id': client_id,
                'client_secret': client_secret,
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [redirect_uri],
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=scopes,
            redirect_uri=redirect_uri,
        )

    def get_auth_url(self, state=None):
        """Generate Google OAuth2 authorization URL.

        Returns:
            Tuple of (auth_url, state).
        """
        flow = self._create_flow()
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
            state=state,
        )
        return auth_url, state

    def handle_callback(self, authorization_response_url):
        """Exchange authorization code for credentials.

        Fetches the token, retrieves the user's email via the Gmail API,
        stores the encrypted token in the database, and returns the email.

        Args:
            authorization_response_url: The full callback URL with auth code.

        Returns:
            The authenticated user's email address.
        """
        flow = self._create_flow()
        # Google may return additional scopes (openid, userinfo) beyond
        # what we requested. Allow the extra scopes without raising.
        os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
        flow.fetch_token(authorization_response=authorization_response_url)
        del os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE']
        credentials = flow.credentials

        # Get the email address from Gmail profile
        service = build('gmail', 'v1', credentials=credentials)
        profile = service.users().getProfile(userId='me').execute()
        email_address = profile['emailAddress']

        # Build token data for storage
        token_data = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': list(credentials.scopes) if credentials.scopes else [],
        }
        encrypted = self._encrypt_token(json.dumps(token_data))

        # Save to DB (import inside to avoid circular imports)
        from database import db
        from models import GmailToken

        # Deactivate any existing tokens
        GmailToken.query.update({'is_active': False})

        # Create or update token for this email
        existing = GmailToken.query.filter_by(
            email_address=email_address
        ).first()
        if existing:
            existing.token_json = encrypted
            existing.is_active = True
        else:
            token = GmailToken(
                email_address=email_address,
                token_json=encrypted,
                is_active=True,
            )
            db.session.add(token)

        db.session.commit()
        return email_address

    def get_credentials(self):
        """Get valid OAuth2 credentials, refreshing if expired.

        Returns:
            google.oauth2.credentials.Credentials instance.

        Raises:
            GmailNotConnectedError: If no active token exists.
        """
        from database import db
        from models import GmailToken

        token_record = GmailToken.query.filter_by(is_active=True).first()
        if not token_record:
            raise GmailNotConnectedError(
                'No active Gmail connection. Please connect via /settings.'
            )

        token_data = json.loads(self._decrypt_token(token_record.token_json))

        creds = Credentials(
            token=token_data['token'],
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get(
                'token_uri', 'https://oauth2.googleapis.com/token'
            ),
            client_id=token_data.get('client_id'),
            client_secret=token_data.get('client_secret'),
            scopes=token_data.get('scopes', []),
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Update stored token with refreshed access token
            token_data['token'] = creds.token
            token_record.token_json = self._encrypt_token(
                json.dumps(token_data)
            )
            db.session.commit()

        return creds

    def get_service(self):
        """Get an authenticated Gmail API service instance.

        Returns:
            googleapiclient.discovery.Resource for Gmail v1.

        Raises:
            GmailNotConnectedError: If no active token exists.
        """
        creds = self.get_credentials()
        return build('gmail', 'v1', credentials=creds)

    def get_connected_email(self):
        """Get the currently connected email address.

        Returns:
            The email address string, or None if not connected.
        """
        from models import GmailToken

        token = GmailToken.query.filter_by(is_active=True).first()
        return token.email_address if token else None

    def disconnect(self):
        """Disconnect Gmail by deactivating all stored tokens."""
        from database import db
        from models import GmailToken

        GmailToken.query.update({'is_active': False})
        db.session.commit()

    def is_connected(self):
        """Check if Gmail is currently connected.

        Returns:
            True if an active token exists, False otherwise.
        """
        from models import GmailToken

        return GmailToken.query.filter_by(is_active=True).first() is not None


# Singleton instance for use with the app factory pattern
gmail_auth = GmailAuth()

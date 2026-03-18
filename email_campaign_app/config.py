import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{os.path.join(basedir, "data", "campaign.db")}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    FERNET_KEY = os.environ.get('FERNET_KEY', '')  # Must be set in production
    GMAIL_CLIENT_SECRET_PATH = os.environ.get(
        'GMAIL_CLIENT_SECRET_PATH',
        os.path.join(basedir, 'data', 'client_secret.json')
    )
    GMAIL_SCOPES = [
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.modify',
    ]
    REDIRECT_URI = os.environ.get(
        'OAUTH_REDIRECT_URI',
        'https://campaign.example.com/gmail/callback'
    )
    # Gmail send OAuth client (separate from login client)
    GMAIL_CLIENT_ID = os.environ.get('GMAIL_CLIENT_ID', '')
    GMAIL_CLIENT_SECRET = os.environ.get('GMAIL_CLIENT_SECRET', '')


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'test-secret-key'
    FERNET_KEY = ''  # Will be generated in test fixtures

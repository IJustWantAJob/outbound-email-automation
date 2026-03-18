"""Tests for authentication (Google OAuth, session protection, role enforcement)."""

import pytest

from app import create_app
from config import TestConfig
from database import db


class AuthTestConfig(TestConfig):
    """TestConfig with auth ENABLED."""
    LOGIN_DISABLED = False
    GOOGLE_LOGIN_CLIENT_ID = 'test-client-id'
    GOOGLE_LOGIN_CLIENT_SECRET = 'test-client-secret'
    ADMIN_EMAIL = 'admin@example.com'
    ALLOWED_DOMAINS = ['@example.com']


@pytest.fixture
def auth_app():
    """Create app with authentication enabled."""
    app = create_app(AuthTestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def auth_client(auth_app):
    return auth_app.test_client()


def _simulate_login(client, email='admin@example.com', name='Test User'):
    """Simulate a successful Google OAuth login by setting session directly."""
    with client.session_transaction() as sess:
        sess['authenticated'] = True
        sess['user_email'] = email
        sess['user_name'] = name
        sess['user_role'] = 'admin' if email == 'admin@example.com' else 'viewer'


@pytest.fixture
def admin_client(auth_app):
    """Client logged in as admin."""
    client = auth_app.test_client()
    _simulate_login(client, email='admin@example.com')
    return client


@pytest.fixture
def viewer_client(auth_app):
    """Client logged in as viewer."""
    client = auth_app.test_client()
    _simulate_login(client, email='viewer@example.com')
    return client


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------

class TestLoginPage:
    def test_login_page_renders(self, auth_client):
        resp = auth_client.get('/login')
        assert resp.status_code == 200
        assert b'Sign in with Google' in resp.data

    def test_login_page_shows_brand(self, auth_client):
        resp = auth_client.get('/login')
        assert b'Email Campaign' in resp.data
        assert b'Manager' in resp.data

    def test_login_error_domain(self, auth_client):
        resp = auth_client.get('/login?error=domain')
        assert resp.status_code == 200
        assert b'not authorized' in resp.data

    def test_login_error_failed(self, auth_client):
        resp = auth_client.get('/login?error=failed')
        assert resp.status_code == 200
        assert b'failed' in resp.data.lower()


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------

class TestOAuthFlow:
    def test_auth_google_redirects(self, auth_client):
        resp = auth_client.get('/auth/google', follow_redirects=False)
        assert resp.status_code == 302
        assert 'accounts.google.com' in resp.headers['Location']

    def test_auth_callback_rejects_bad_state(self, auth_client):
        resp = auth_client.get('/auth/callback?state=bad&code=x', follow_redirects=False)
        assert resp.status_code == 302
        assert 'error=failed' in resp.headers['Location']

    def test_already_logged_in_redirects_from_login(self, admin_client):
        resp = admin_client.get('/login', follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'] == '/'


# ---------------------------------------------------------------------------
# Route protection
# ---------------------------------------------------------------------------

class TestRouteProtection:
    def test_dashboard_requires_login(self, auth_client):
        resp = auth_client.get('/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_contacts_requires_login(self, auth_client):
        resp = auth_client.get('/contacts', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_campaigns_requires_login(self, auth_client):
        resp = auth_client.get('/campaigns', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_api_requires_login(self, auth_client):
        resp = auth_client.get('/api/campaigns', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_settings_requires_login(self, auth_client):
        resp = auth_client.get('/settings', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_health_check_is_public(self, auth_client):
        resp = auth_client.get('/api/health')
        assert resp.status_code == 200
        assert resp.json == {'status': 'ok'}

    def test_static_files_are_public(self, auth_client):
        resp = auth_client.get('/static/css/style.css')
        assert resp.status_code == 200

    def test_authenticated_user_can_access_dashboard(self, admin_client):
        resp = admin_client.get('/')
        assert resp.status_code == 200

    def test_authenticated_user_can_access_contacts(self, admin_client):
        resp = admin_client.get('/contacts')
        assert resp.status_code == 200

    def test_authenticated_user_can_access_api(self, admin_client):
        resp = admin_client.get('/api/campaigns')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Role enforcement (viewer = read-only)
# ---------------------------------------------------------------------------

class TestViewerReadOnly:
    def test_viewer_can_get_dashboard(self, viewer_client):
        resp = viewer_client.get('/')
        assert resp.status_code == 200

    def test_viewer_can_get_contacts(self, viewer_client):
        resp = viewer_client.get('/contacts')
        assert resp.status_code == 200

    def test_viewer_can_get_api_campaigns(self, viewer_client):
        resp = viewer_client.get('/api/campaigns')
        assert resp.status_code == 200

    def test_viewer_cannot_post_campaign(self, viewer_client):
        resp = viewer_client.post(
            '/api/campaigns',
            json={'name': 'test'},
            content_type='application/json',
        )
        assert resp.status_code == 403

    def test_viewer_cannot_put_campaign(self, viewer_client):
        resp = viewer_client.put(
            '/api/campaigns/1',
            json={'name': 'test'},
            content_type='application/json',
        )
        assert resp.status_code == 403

    def test_viewer_cannot_delete_contact(self, viewer_client):
        resp = viewer_client.delete('/api/contacts/1')
        assert resp.status_code == 403

    def test_viewer_cannot_send_email(self, viewer_client):
        resp = viewer_client.post('/api/emails/1/send-now')
        assert resp.status_code == 403

    def test_viewer_cannot_import_contacts(self, viewer_client):
        resp = viewer_client.post(
            '/api/contacts/import-json',
            json={'contacts': []},
            content_type='application/json',
        )
        assert resp.status_code == 403

    def test_viewer_403_has_message(self, viewer_client):
        resp = viewer_client.post(
            '/api/campaigns',
            json={'name': 'test'},
            content_type='application/json',
        )
        data = resp.get_json()
        assert 'View-only' in data['error']

    def test_admin_can_post_campaign(self, admin_client):
        resp = admin_client.post(
            '/api/campaigns',
            json={'name': 'Admin Campaign'},
            content_type='application/json',
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_logout_clears_session(self, admin_client):
        resp = admin_client.get('/logout', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_after_logout_cannot_access_dashboard(self, admin_client):
        admin_client.get('/logout')
        resp = admin_client.get('/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    def test_hsts_header_present(self, auth_client):
        resp = auth_client.get('/login')
        assert 'Strict-Transport-Security' in resp.headers
        assert 'max-age=31536000' in resp.headers['Strict-Transport-Security']

    def test_csp_header_present(self, auth_client):
        resp = auth_client.get('/login')
        assert 'Content-Security-Policy' in resp.headers
        csp = resp.headers['Content-Security-Policy']
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_x_frame_options_deny(self, auth_client):
        resp = auth_client.get('/login')
        assert resp.headers.get('X-Frame-Options') == 'DENY'


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_rate_limiter_exists_on_app(self, auth_app):
        assert hasattr(auth_app, 'limiter')

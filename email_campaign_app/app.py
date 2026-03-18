import logging
import os
import secrets
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from urllib.parse import urlencode

import requests as http_requests
from flask import Flask, redirect, render_template, request, session, url_for, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config


def setup_logging(app):
    """Configure rotating file logger for the application."""
    log_dir = os.path.join(app.root_path, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=1024 * 1024,  # 1 MB
        backupCount=5,
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s] %(message)s'
    ))
    file_handler.setLevel(logging.INFO)

    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Email Campaign Manager starting')


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Trust Cloudflare proxy headers
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Rate limiter (uses client IP from ProxyFix)
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[],
        storage_uri='memory://',
    )
    app.limiter = limiter

    # Set up logging (skip in testing to avoid file I/O in tests)
    if not app.config.get('TESTING'):
        setup_logging(app)

    # Init database
    from database import db
    db.init_app(app)

    # Enforce FERNET_KEY in production (Gmail tokens must be encrypted)
    if not app.config.get('TESTING') and not app.config.get('FERNET_KEY'):
        raise RuntimeError(
            'FERNET_KEY must be set in production. Generate one with: '
            'python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Strict-Transport-Security'] = (
            'max-age=31536000; includeSubDomains'
        )
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        return response

    # Configure secure cookies for production
    if not app.config.get('TESTING'):
        app.config['SESSION_COOKIE_SECURE'] = True
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Session lifetime
    app.permanent_session_lifetime = timedelta(
        seconds=app.config.get('PERMANENT_SESSION_LIFETIME', 86400 * 7)
    )

    # --- Authentication (Google OAuth) ---
    PUBLIC_PATHS = {'/login', '/logout', '/auth/google', '/auth/callback', '/api/health', '/static'}

    ADMIN_EMAIL = app.config.get('ADMIN_EMAIL', 'admin@example.com').lower()
    ALLOWED_DOMAINS = app.config.get('ALLOWED_DOMAINS', ['@example.com'])

    # Routes that viewers (non-admin) ARE allowed to use even with POST
    VIEWER_ALLOWED_PATHS = {
        '/login', '/logout', '/auth/google', '/auth/callback',
    }

    @app.before_request
    def require_login():
        """Require Google OAuth authentication for all routes except public paths."""
        if app.config.get('LOGIN_DISABLED'):
            return  # Skip auth in tests

        # Allow public paths and static files
        if request.path in PUBLIC_PATHS:
            return
        if request.path.startswith('/static/'):
            return

        # Check session
        if not session.get('authenticated'):
            return redirect(url_for('login'))

    @app.before_request
    def enforce_viewer_readonly():
        """Block mutating requests (POST/PUT/DELETE) for non-admin users."""
        if app.config.get('LOGIN_DISABLED'):
            return

        # Only enforce on authenticated, non-public paths
        if not session.get('authenticated'):
            return
        if request.path in VIEWER_ALLOWED_PATHS:
            return
        if request.path.startswith('/static/'):
            return

        # Admin can do everything
        if session.get('user_role') == 'admin':
            return

        # Viewers can only read (GET/HEAD/OPTIONS)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'View-only access. Contact the administrator for edit permissions.'}), 403
            return render_template('errors/403.html', active_page=''), 403

    @app.context_processor
    def inject_user_context():
        """Make user info available in all templates."""
        from models import SenderProfile
        profile = SenderProfile.query.first()
        return {
            'user_email': session.get('user_email', ''),
            'user_name': session.get('user_name', ''),
            'user_role': session.get('user_role', 'viewer'),
            'has_profile': profile is not None,
            'profile_company': profile.company_name if profile else '',
        }

    @app.route('/login')
    def login():
        if session.get('authenticated'):
            return redirect('/')
        error = request.args.get('error')
        error_messages = {
            'domain': 'Access denied. Your email domain is not authorized.',
            'failed': 'Authentication failed. Please try again.',
        }
        return render_template('login.html', error=error_messages.get(error))

    @app.route('/auth/google')
    @limiter.limit('10 per minute')
    def auth_google():
        """Initiate Google OAuth2 flow."""
        client_id = app.config.get('GOOGLE_LOGIN_CLIENT_ID')
        if not client_id:
            return 'Google OAuth not configured. Set GOOGLE_LOGIN_CLIENT_ID.', 500

        state = secrets.token_urlsafe(32)
        session['oauth_state'] = state

        redirect_uri = request.url_root.rstrip('/') + '/auth/callback'
        params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'openid email profile',
            'access_type': 'online',
            'prompt': 'select_account',
            'state': state,
        }
        auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)
        return redirect(auth_url)

    @app.route('/auth/callback')
    def auth_callback():
        """Handle Google OAuth2 callback."""
        # Validate state
        stored_state = session.pop('oauth_state', None)
        received_state = request.args.get('state')
        if not stored_state or stored_state != received_state:
            return redirect('/login?error=failed')

        error = request.args.get('error')
        code = request.args.get('code')
        if error or not code:
            return redirect('/login?error=failed')

        client_id = app.config.get('GOOGLE_LOGIN_CLIENT_ID')
        client_secret = app.config.get('GOOGLE_LOGIN_CLIENT_SECRET')
        redirect_uri = request.url_root.rstrip('/') + '/auth/callback'

        # Exchange code for tokens
        try:
            token_resp = http_requests.post(
                'https://oauth2.googleapis.com/token',
                data={
                    'code': code,
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'redirect_uri': redirect_uri,
                    'grant_type': 'authorization_code',
                },
                timeout=10,
            )
            token_data = token_resp.json()
        except Exception:
            return redirect('/login?error=failed')

        if 'access_token' not in token_data:
            return redirect('/login?error=failed')

        # Get user info
        try:
            user_resp = http_requests.get(
                'https://www.googleapis.com/oauth2/v2/userinfo',
                headers={'Authorization': f'Bearer {token_data["access_token"]}'},
                timeout=10,
            )
            user_info = user_resp.json()
        except Exception:
            return redirect('/login?error=failed')

        email = (user_info.get('email') or '').lower()

        # Domain check
        if not any(email.endswith(d) for d in ALLOWED_DOMAINS):
            app.logger.warning(f'Blocked login from unauthorized domain: {email}')
            return redirect('/login?error=domain')

        # Set session
        session.permanent = True
        session['authenticated'] = True
        session['user_email'] = email
        session['user_name'] = user_info.get('name', '')
        session['user_role'] = 'admin' if email == ADMIN_EMAIL else 'viewer'

        app.logger.info(
            f'User {email} logged in (role={session["user_role"]}) from {request.remote_addr}'
        )
        return redirect('/')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    # Init Gmail OAuth
    from gmail.auth import gmail_auth
    gmail_auth.init_app(app)

    # Register blueprints
    from routes.gmail_auth import gmail_bp
    app.register_blueprint(gmail_bp)

    from routes.api import api_bp
    app.register_blueprint(api_bp)

    from routes.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)

    from routes.reports import reports_bp
    app.register_blueprint(reports_bp)

    # Error handlers
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html', active_page=''), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html', active_page=''), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error('Internal server error: %s', e)
        return render_template('errors/500.html', active_page=''), 500

    # Create tables
    with app.app_context():
        from models import (
            Campaign, Contact, Email, Reply, Metric, GmailToken, Report,
            SenderProfile, ApiKey,
        )
        db.create_all()

    # Initialize scheduler (only in non-testing mode)
    if not app.config.get('TESTING'):
        from scheduler.engine import init_scheduler
        init_scheduler(app)

    # Register a simple health check
    @app.route('/api/health')
    def health_check():
        return {'status': 'ok'}

    return app

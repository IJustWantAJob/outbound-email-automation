import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask, render_template, request
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

    # Set up logging (skip in testing to avoid file I/O in tests)
    if not app.config.get('TESTING'):
        setup_logging(app)

    # Init database
    from database import db
    db.init_app(app)

    # Warn if FERNET_KEY was auto-generated (tokens won't survive restarts)
    if not app.config.get('TESTING') and not os.environ.get('FERNET_KEY'):
        app.logger.warning(
            'FERNET_KEY not set — using an auto-generated key. '
            'Gmail tokens will not survive app restarts. '
            'For production, set FERNET_KEY in your environment. '
            'Generate one with: python3 -c '
            '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
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

    # --- No authentication required (open-source mode) ---
    # To add authentication back, implement middleware here.

    @app.context_processor
    def inject_user_context():
        """Make profile info available in all templates."""
        from models import SenderProfile
        profile = SenderProfile.query.first()
        return {
            'has_profile': profile is not None,
            'profile_company': profile.company_name if profile else '',
        }

    # Init Gmail OAuth (for sending emails, not login)
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

    # Ensure data directory exists (gitignored, so missing on fresh clones)
    data_dir = os.path.join(app.root_path, 'data')
    os.makedirs(data_dir, exist_ok=True)

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

"""Gmail OAuth2 callback route handlers.

Handles the OAuth2 redirect flow: initiating authorization,
processing the callback, storing encrypted tokens, and re-authorization.
"""

import logging
import secrets

from flask import Blueprint, current_app, jsonify, redirect, request, session

from gmail.auth import gmail_auth

gmail_bp = Blueprint('gmail', __name__, url_prefix='/gmail')
logger = logging.getLogger(__name__)


@gmail_bp.route('/connect')
def connect():
    """Initiate the OAuth2 flow by redirecting to Google's consent screen."""
    try:
        state = secrets.token_urlsafe(32)
        session['oauth_state'] = state
        auth_url, _ = gmail_auth.get_auth_url(state=state)
        return redirect(auth_url)
    except FileNotFoundError as e:
        logger.error('Gmail OAuth config error: %s', e)
        return redirect('/settings?error=gmail_config')
    except Exception as e:
        logger.error('Gmail connect error: %s', e)
        return redirect('/settings?error=gmail_connect')


@gmail_bp.route('/callback')
def callback():
    """Handle the OAuth2 callback from Google.

    Validates the CSRF state parameter, exchanges the authorization code
    for credentials, and stores the encrypted token in the database.
    """
    # Validate CSRF state
    stored_state = session.pop('oauth_state', None)
    received_state = request.args.get('state')

    if not stored_state or stored_state != received_state:
        return (
            jsonify({'error': 'Invalid state parameter. Possible CSRF attack.'}),
            403,
        )

    # Check for OAuth error (e.g., user denied access)
    error = request.args.get('error')
    if error:
        return jsonify({'error': f'OAuth error: {error}'}), 400

    try:
        email = gmail_auth.handle_callback(request.url)
        return redirect(
            f'/settings?gmail_connected=true&email={email}'
        )
    except Exception as e:
        logger.error('Gmail callback error: %s', e)
        return (
            jsonify({'error': f'Failed to connect Gmail: {str(e)}'}),
            500,
        )


@gmail_bp.route('/status')
def status():
    """Return the current Gmail connection status as JSON."""
    connected = gmail_auth.is_connected()
    email = gmail_auth.get_connected_email() if connected else None
    return jsonify({
        'connected': connected,
        'email': email,
    })


@gmail_bp.route('/disconnect', methods=['POST'])
def disconnect():
    """Disconnect Gmail by deactivating all stored tokens."""
    gmail_auth.disconnect()
    return jsonify({'status': 'disconnected'})


@gmail_bp.route('/reauthorize')
def reauthorize():
    """Re-authorize Gmail without disconnecting first.

    Initiates a fresh OAuth2 consent flow. On successful callback,
    the existing token is replaced with the new one (handled by
    handle_callback which does upsert by email).
    """
    try:
        state = secrets.token_urlsafe(32)
        session['oauth_state'] = state
        auth_url, _ = gmail_auth.get_auth_url(state=state)
        return redirect(auth_url)
    except FileNotFoundError as e:
        logger.error('Gmail OAuth config error during reauthorize: %s', e)
        return redirect('/settings?error=gmail_config')
    except Exception as e:
        logger.error('Gmail reauthorize error: %s', e)
        return redirect('/settings?error=gmail_connect')

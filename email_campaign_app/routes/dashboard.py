"""Dashboard route handlers.

Serves the main dashboard and page views using Jinja2 templates.
All data is fetched client-side from the /api/* JSON endpoints,
keeping the architecture cleanly separated.
"""

from flask import Blueprint, flash, redirect, render_template

from database import db
from models import Campaign, Contact, Email, SenderProfile

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
def index():
    """Dashboard page — shows onboarding if no profile exists."""
    profile = SenderProfile.query.first()
    if not profile:
        return render_template('onboarding.html', active_page='dashboard')
    return render_template('dashboard.html', active_page='dashboard')


@dashboard_bp.route('/onboarding')
def onboarding():
    """Onboarding page — accessible anytime to redo setup."""
    return render_template('onboarding.html', active_page='dashboard')


@dashboard_bp.route('/settings/profile')
def profile_settings():
    """Edit sender profile page."""
    profile = SenderProfile.query.first()
    if not profile:
        return redirect('/')
    return render_template('profile_settings.html', active_page='settings')


@dashboard_bp.route('/contacts')
def contact_list():
    """Contact list page."""
    return render_template('contacts/list.html', active_page='contacts')


@dashboard_bp.route('/contacts/new')
def contact_new():
    """New contact form page."""
    return render_template('contacts/form.html', active_page='contacts', editing=False)


@dashboard_bp.route('/contacts/import')
def contact_import():
    """Import page."""
    return render_template('contacts/import.html', active_page='contacts')


@dashboard_bp.route('/contacts/<int:contact_id>')
def contact_detail(contact_id):
    """Contact detail page."""
    contact = db.session.get(Contact, contact_id)
    if not contact:
        flash('Contact not found.', 'error')
        return render_template('errors/404.html', active_page='contacts'), 404
    return render_template(
        'contacts/detail.html',
        active_page='contacts',
        contact_id=contact_id,
    )


@dashboard_bp.route('/campaigns')
def campaign_list():
    """Campaign list page."""
    return render_template('campaigns/list.html', active_page='campaigns')


@dashboard_bp.route('/campaigns/<int:campaign_id>')
def campaign_detail(campaign_id):
    """Campaign detail / settings page."""
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        flash('Campaign not found.', 'error')
        return render_template('errors/404.html', active_page='campaigns'), 404
    return render_template(
        'campaigns/detail.html',
        active_page='campaigns',
        campaign_id=campaign_id,
    )


@dashboard_bp.route('/emails/queue')
def email_queue():
    """Email queue page."""
    return render_template('emails/queue.html', active_page='queue')


@dashboard_bp.route('/emails/<int:email_id>/preview')
def email_preview(email_id):
    """Email preview page."""
    email = db.session.get(Email, email_id)
    if not email:
        flash('Email not found.', 'error')
        return render_template('errors/404.html', active_page='queue'), 404
    return render_template(
        'emails/preview.html',
        active_page='queue',
        email_id=email_id,
    )


@dashboard_bp.route('/reports')
def reports():
    """Reports page."""
    return render_template('reports/list.html', active_page='reports')


@dashboard_bp.route('/settings')
def settings():
    """Settings page (Gmail connection)."""
    return render_template('settings.html', active_page='settings')

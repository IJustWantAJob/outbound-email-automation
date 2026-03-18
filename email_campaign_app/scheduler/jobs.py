"""Scheduled job functions. Each wraps its logic in the Flask app context."""

import logging

from scheduler.engine import get_app

logger = logging.getLogger('scheduler')


def process_email_queue():
    """Send any emails whose scheduled_at is past and status is 'scheduled'."""
    app = get_app()
    if not app:
        return
    with app.app_context():
        from scheduler.queue import process_queue

        process_queue()


def check_replies_job():
    """Check Gmail for replies to sent emails."""
    app = get_app()
    if not app:
        return
    with app.app_context():
        from gmail.reader import check_for_replies

        try:
            check_for_replies()
        except Exception as e:
            logger.error(f"Reply check failed: {e}")


def generate_daily_queue_job():
    """Generate today's send queue for all active campaigns."""
    app = get_app()
    if not app:
        return
    with app.app_context():
        from scheduler.queue import generate_daily_queue_for_active_campaigns

        generate_daily_queue_for_active_campaigns()


def generate_daily_report_job():
    """Generate daily summary reports for active campaigns."""
    app = get_app()
    if not app:
        return
    with app.app_context():
        from routes.reports import generate_daily_summary
        from models import Campaign

        campaigns = Campaign.query.filter_by(status='active').all()
        for campaign in campaigns:
            try:
                generate_daily_summary(campaign.id)
            except Exception as e:
                logger.error(
                    f"Daily report failed for campaign {campaign.id}: {e}"
                )

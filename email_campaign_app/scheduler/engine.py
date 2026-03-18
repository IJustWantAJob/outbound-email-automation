"""APScheduler configuration and lifecycle management."""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

scheduler = BackgroundScheduler()
_app = None


def init_scheduler(app):
    """Initialize the scheduler with the Flask app context.

    Call this in the app factory after all other initialization.
    """
    global _app
    _app = app

    if scheduler.running:
        return scheduler

    from scheduler.jobs import (
        process_email_queue,
        check_replies_job,
        generate_daily_queue_job,
        generate_daily_report_job,
    )

    # Process email queue every 2 minutes (sends due emails)
    scheduler.add_job(
        process_email_queue,
        IntervalTrigger(minutes=2),
        id='process_queue',
        replace_existing=True,
        max_instances=1,
    )

    # Check for replies every 15 minutes
    scheduler.add_job(
        check_replies_job,
        IntervalTrigger(minutes=15),
        id='check_replies',
        replace_existing=True,
        max_instances=1,
    )

    # Generate daily queue at 7 AM Pacific
    scheduler.add_job(
        generate_daily_queue_job,
        CronTrigger(hour=7, minute=0, timezone='America/Los_Angeles'),
        id='daily_queue',
        replace_existing=True,
        max_instances=1,
    )

    # Generate daily report at 6 PM Pacific
    scheduler.add_job(
        generate_daily_report_job,
        CronTrigger(hour=18, minute=0, timezone='America/Los_Angeles'),
        id='daily_report',
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    return scheduler


def shutdown_scheduler():
    """Shut down the scheduler if it is running."""
    if scheduler.running:
        scheduler.shutdown(wait=False)


def get_app():
    """Return the Flask app stored during init_scheduler."""
    return _app

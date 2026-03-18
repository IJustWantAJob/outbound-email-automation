"""Tests for APScheduler engine initialization and lifecycle."""

import os
import sys

import pytest

# Ensure the app package is importable
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
)

from app import create_app
from config import TestConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def non_testing_app():
    """Create an app with TESTING=False so the scheduler initializes."""

    class SchedulerTestConfig(TestConfig):
        TESTING = False
        FERNET_KEY = 'Scn38WNUambKsuQq0ZoZLklhpmR5LiTPQeOUpAy8PcY='

    app = create_app(SchedulerTestConfig)
    yield app

    # Clean up: shut down the scheduler after the test
    from scheduler.engine import shutdown_scheduler
    shutdown_scheduler()


@pytest.fixture
def testing_app():
    """Create an app with TESTING=True (scheduler should NOT start)."""
    app = create_app(TestConfig)
    yield app


# ---------------------------------------------------------------------------
# Engine Tests
# ---------------------------------------------------------------------------


class TestSchedulerEngine:

    def test_scheduler_initializes(self, non_testing_app):
        """init_scheduler doesn't crash and scheduler is running."""
        from scheduler.engine import scheduler

        assert scheduler.running is True

    def test_scheduler_has_jobs(self, non_testing_app):
        """After init, 4 jobs are registered."""
        from scheduler.engine import scheduler

        jobs = scheduler.get_jobs()
        job_ids = {j.id for j in jobs}
        assert 'process_queue' in job_ids
        assert 'check_replies' in job_ids
        assert 'daily_queue' in job_ids
        assert 'daily_report' in job_ids
        assert len(jobs) == 4

    def test_scheduler_shutdown(self, non_testing_app):
        """shutdown_scheduler works cleanly."""
        from scheduler.engine import scheduler, shutdown_scheduler

        assert scheduler.running is True
        shutdown_scheduler()
        assert scheduler.running is False

    def test_scheduler_not_started_in_testing(self, testing_app):
        """Scheduler should NOT be started when TESTING=True."""
        # The scheduler module-level object might be running from a previous
        # test, so we check that create_app with TESTING=True does NOT call
        # init_scheduler. We verify by checking the app stored in engine.
        from scheduler.engine import get_app

        # In testing mode, _app should not have been set to this app
        # (it may be set from a previous non-testing test, but won't be
        # the testing_app).
        stored_app = get_app()
        if stored_app is not None:
            assert stored_app is not testing_app

    def test_get_app_returns_flask_app(self, non_testing_app):
        """get_app returns the Flask app passed to init_scheduler."""
        from scheduler.engine import get_app

        app = get_app()
        assert app is non_testing_app

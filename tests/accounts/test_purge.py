"""Unit under test: `accounts.purge.AccountsPurge`, the daily housekeeping of the sign-in tables (`accounts.purge`
on beat).

Why: the mail log holds addresses, and the plan keeps personal data only as long as abuse work and support need it
(30 days).
What is forgotten must be forgotten on time, and what is recent must stay.

Use cases:
- mail log rows older than the retention are deleted and newer ones stay, whatever their status
- the report counts what was deleted, and a second run deletes nothing
- the retention is a setting (`MAIL_LOG_RETENTION_DAYS`)
- the Celery task runs the purge and reports the counts
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone
from support.clock import FakeClock

from accounts.models import OutboundMail
from accounts.purge import AccountsPurge
from accounts.tasks import purge

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 12, 3, 0, tzinfo=UTC)


def mail(days_old, status="sent"):
    return OutboundMail.objects.create(
        kind="signup_code",
        to_email="a@example.com",
        backend="outbox",
        status=status,
        created_at=NOW - timedelta(days=days_old),
    )


def test_old_mail_log_rows_go_and_recent_ones_stay(settings):
    settings.MAIL_LOG_RETENTION_DAYS = 30
    old_sent, old_failed, recent_sent, recent_queued = mail(31), mail(45, "failed"), mail(29), mail(1, "queued")

    report = AccountsPurge(clock=FakeClock(NOW)).run()

    assert set(OutboundMail.objects.values_list("pk", flat=True)) == {recent_sent.pk, recent_queued.pk}
    assert report.mail == 2 and old_sent.pk and old_failed.pk
    assert AccountsPurge(clock=FakeClock(NOW)).run().mail == 0


def test_the_retention_is_a_setting(settings):
    settings.MAIL_LOG_RETENTION_DAYS = 7
    mail(8), mail(6)

    AccountsPurge(clock=FakeClock(NOW)).run()

    assert OutboundMail.objects.count() == 1


def test_the_celery_task_runs_the_purge(settings):
    settings.MAIL_LOG_RETENTION_DAYS = 0
    OutboundMail.objects.create(
        kind="signup_code", to_email="a@example.com", backend="outbox", created_at=timezone.now() - timedelta(days=1)
    )

    assert purge.name == "accounts.purge"
    assert purge.apply().get() == {"mail": 1}

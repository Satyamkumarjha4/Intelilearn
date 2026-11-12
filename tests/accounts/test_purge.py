"""Unit under test: `accounts.purge.AccountsPurge`, the daily housekeeping of the sign-in tables (`accounts.purge`
on beat).

Why: the mail log holds addresses, and the plan keeps personal data only as long as abuse work and support need it
(30 days).
What is forgotten must be forgotten on time, and what is recent must stay.

Use cases:
- mail log rows older than the retention are deleted and newer ones stay, whatever their status
- the report counts what was deleted, and a second run deletes nothing
- the retention is a setting (`MAIL_LOG_RETENTION_DAYS`)
- a pending sign-up past its expiry goes with its codes; a live one stays
- spent, dead and expired codes go after `CODE_LOG_RETENTION_DAYS`; recent ones and live ones stay
- where-from records go after `SIGNUP_RECORD_RETENTION_DAYS`
- the Celery task runs the purge and reports the counts
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone
from support.clock import FakeClock

from accounts.models import OutboundMail, PendingSignup, SignupRecord, VerificationCode
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


def pending(hours_to_expiry, email="p@example.com"):
    return PendingSignup.objects.create(
        email=email, email_canonical=email, name="P", password_hash="x", terms_version="v",
        terms_accepted_at=NOW, created_at=NOW - timedelta(hours=24), expires_at=NOW + timedelta(hours=hours_to_expiry),
    )  # fmt: skip


def code(email, **when):
    return VerificationCode.objects.create(
        purpose="signup",
        email_canonical=email,
        code_hash="h",
        max_attempts=5,
        created_at=NOW - timedelta(days=9),
        expires_at=when.pop("expires_at", NOW + timedelta(days=1)),
        **when,
    )


def test_a_sign_up_that_never_got_its_code_goes_with_its_codes_and_a_live_one_stays():
    stale, live = pending(-1, "stale@example.com"), pending(5, "live@example.com")
    code("stale@example.com", pending=stale), code("live@example.com", pending=live)

    report = AccountsPurge(clock=FakeClock(NOW)).run()

    assert list(PendingSignup.objects.values_list("email", flat=True)) == ["live@example.com"]
    assert report.pending == 1 and list(VerificationCode.objects.values_list("email_canonical", flat=True)) == [
        "live@example.com"
    ]


def test_spent_dead_and_expired_codes_go_after_their_retention_and_a_recent_or_live_one_stays(settings):
    settings.CODE_LOG_RETENTION_DAYS = 7
    old, recent = NOW - timedelta(days=8), NOW - timedelta(days=2)
    code("a@example.com", consumed_at=old), code("b@example.com", invalidated_at=old)
    code("c@example.com", expires_at=old)
    code("d@example.com", consumed_at=recent), code("e@example.com")  # recently spent, and still live

    report = AccountsPurge(clock=FakeClock(NOW)).run()

    assert report.codes == 3
    assert sorted(VerificationCode.objects.values_list("email_canonical", flat=True)) == [
        "d@example.com",
        "e@example.com",
    ]


def test_where_from_records_go_after_thirty_days(settings, user, other_user):
    settings.SIGNUP_RECORD_RETENTION_DAYS = 30
    for owner, days in ((user, 31), (other_user, 29)):
        SignupRecord.objects.create(
            user=owner,
            ip="203.0.113.1",
            email_domain="example.com",
            method="code",
            created_at=NOW - timedelta(days=days),
        )

    report = AccountsPurge(clock=FakeClock(NOW)).run()

    assert report.signup_records == 1 and list(SignupRecord.objects.values_list("user_id", flat=True)) == [
        other_user.pk
    ]


def test_the_celery_task_runs_the_purge(settings):
    settings.MAIL_LOG_RETENTION_DAYS = 0
    OutboundMail.objects.create(
        kind="signup_code", to_email="a@example.com", backend="outbox", created_at=timezone.now() - timedelta(days=1)
    )

    assert purge.name == "accounts.purge"
    assert purge.apply().get() == {"mail": 1, "pending": 0, "codes": 0, "signup_records": 0}

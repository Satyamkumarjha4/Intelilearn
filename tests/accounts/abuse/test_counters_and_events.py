"""Unit under test: `accounts.abuse.counters.AbuseCounters`, `accounts.abuse.events.AuthEvents` and
`accounts.abuse.records.SignupRecords`: the numbers behind the console's abuse board.

Why: the board is how staff notice that someone is farming sign-ups, so its numbers must be exactly what happened: the
accounts made, the codes sent, the wrong codes and the refused throwaway addresses, per day, and where the busiest
addresses and email domains in the last day come from. A day with nothing is a row of zeros (a chart has no holes), a
window is a window (an event just outside it is not counted), and no list ever names an email.

Use cases:
- the daily rows cover exactly the last N UTC days, oldest first, today last, and a quiet day is all zeros
- accounts made, codes sent (the three code kinds only), wrong codes, refused throwaway addresses and failed
  challenges are each counted on the day they happened and match the seeded events
- events and records older than the window are not counted
- the top addresses and top domains of the last 24 hours add the sign-ups and the events, most first, ties broken
  stably, at most the limit, and an hour just outside the window is left out
- only the domain of an email is ever kept by an event, a failure to write one is logged and swallowed, and records
  of how an account was made are written once with the domain taken from the canonical email
- locked emails counts only locks that have not ended
"""

from datetime import UTC, datetime, timedelta

import pytest
from support.clock import FakeClock

from accounts.abuse.counters import AbuseCounters
from accounts.abuse.events import AuthEvents
from accounts.abuse.records import SignupRecords
from accounts.models import AuthEvent, EmailLock, OutboundMail, SignupRecord, User

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)


@pytest.fixture
def clock():
    return FakeClock(NOW)


def mail(kind, at):
    OutboundMail.objects.create(kind=kind, to_email="a@example.com", backend="brevo", created_at=at)


def event(kind, at, ip="203.0.113.1", domain=""):
    return AuthEvent.objects.create(kind=kind, ip=ip, email_domain=domain, created_at=at)


def record(user, at, ip="203.0.113.1", domain="example.com", method="code"):
    return SignupRecord.objects.create(user=user, ip=ip, email_domain=domain, method=method, created_at=at)


def test_the_daily_rows_cover_the_last_days_oldest_first_and_a_quiet_day_is_zeros(clock):
    rows = AbuseCounters(clock).daily(days=5)

    assert [r.day.isoformat() for r in rows] == ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    assert all(r.as_dict() | {"day": ""} == {"day": "", "accounts_made": 0, "codes_sent": 0, "failed_checks": 0,
                                              "disposable_refused": 0, "captcha_failed": 0} for r in rows)  # fmt: skip


def test_each_number_is_counted_on_its_own_day_and_matches_what_was_seeded(clock, user, other_user):
    today, yesterday = NOW - timedelta(hours=1), NOW - timedelta(days=1, hours=1)
    record(user, today), record(other_user, yesterday)
    for kind in ("signup_code", "login_code", "reset_code", "owner_notice", "use_google_notice", "takeover_notice"):
        mail(kind, today)  # only the three code kinds are codes sent
    mail("signup_code", yesterday)
    for _ in range(3):
        event("check_failed", today)
    event("disposable_refused", today), event("disposable_refused", yesterday), event("captcha_failed", yesterday)

    today_row, yesterday_row = AbuseCounters(clock).daily(days=3)[-1], AbuseCounters(clock).daily(days=3)[-2]

    assert today_row.as_dict() == {
        "day": "2026-11-13", "accounts_made": 1, "codes_sent": 3, "failed_checks": 3,
        "disposable_refused": 1, "captcha_failed": 0,
    }  # fmt: skip
    assert yesterday_row.as_dict() == {
        "day": "2026-11-12", "accounts_made": 1, "codes_sent": 1, "failed_checks": 0,
        "disposable_refused": 1, "captcha_failed": 1,
    }  # fmt: skip


def test_anything_before_the_window_is_not_counted(clock, user):
    old = NOW - timedelta(days=30)
    record(user, old), mail("signup_code", old), event("check_failed", old)

    assert sum(r.accounts_made + r.codes_sent + r.failed_checks for r in AbuseCounters(clock).daily(days=14)) == 0


def test_the_top_addresses_add_sign_ups_and_events_most_first_and_stop_at_the_limit(clock, user, other_user):
    recent = NOW - timedelta(hours=2)
    record(user, recent, ip="203.0.113.1"), record(other_user, recent, ip="203.0.113.1")
    for _ in range(3):
        event("check_failed", recent, ip="203.0.113.2")
    event("disposable_refused", recent, ip="203.0.113.3")
    event("check_failed", recent, ip=None)  # no address: not a row
    event("check_failed", NOW - timedelta(hours=25), ip="203.0.113.9")  # an hour outside the window

    top = AbuseCounters(clock).top_addresses(hours=24, limit=2)

    assert [(t.name, t.count) for t in top] == [("203.0.113.2", 3), ("203.0.113.1", 2)]
    assert "203.0.113.9" not in [t.name for t in AbuseCounters(clock).top_addresses(hours=24, limit=10)]


def test_the_top_domains_add_sign_ups_and_events_and_leave_out_a_blank_domain(clock, user):
    recent = NOW - timedelta(hours=2)
    record(user, recent, domain="gmail.com")
    (
        event("disposable_refused", recent, domain="mailinator.com"),
        event("disposable_refused", recent, domain="mailinator.com"),
    )
    event("captcha_failed", recent, domain="")  # a failed challenge names no email

    top = AbuseCounters(clock).top_domains(hours=24, limit=5)

    assert [(t.name, t.count) for t in top] == [("mailinator.com", 2), ("gmail.com", 1)]


def test_only_locks_that_have_not_ended_are_counted(clock):
    EmailLock.objects.create(email_canonical="a@example.com", locked_until=NOW + timedelta(minutes=5))
    EmailLock.objects.create(email_canonical="b@example.com", locked_until=NOW - timedelta(minutes=5))
    EmailLock.objects.create(email_canonical="c@example.com", locked_until=None, strikes=2)

    assert AbuseCounters(clock).locked_emails() == 1


def test_an_event_keeps_the_domain_of_an_email_and_never_the_address(clock):
    AuthEvents(clock).record("check_failed", "203.0.113.5", "Ada.Lovelace@School.AC.in")
    AuthEvents(clock).record("captcha_failed", None)
    AuthEvents(clock).record("check_failed", "203.0.113.5", "not-an-address")

    saved = list(AuthEvent.objects.order_by("id").values("kind", "ip", "email_domain", "created_at"))
    assert [(s["kind"], s["ip"], s["email_domain"]) for s in saved] == [
        ("check_failed", "203.0.113.5", "school.ac.in"),
        ("captcha_failed", None, ""),
        ("check_failed", "203.0.113.5", ""),
    ]
    assert all(s["created_at"] == NOW for s in saved) and "lovelace" not in str(saved).lower()


def test_an_event_that_cannot_be_written_is_logged_and_swallowed(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(AuthEvent.objects, "create", broken)

    AuthEvents().record("check_failed", "203.0.113.5", "a@example.com")

    assert "could not record an auth event" in caplog.text


def test_a_signup_record_takes_its_domain_from_the_canonical_email_and_is_found_for_the_account(clock):
    account = User.objects.create_user("Ada.L+x@Gmail.com", password="x" * 12, name="Ada")

    made = SignupRecords(clock).record(account, "203.0.113.7", "code")

    assert (made.email_domain, made.ip, made.method, made.created_at) == ("gmail.com", "203.0.113.7", "code", NOW)
    assert SignupRecords.of(account) == made
    assert SignupRecords.of(User.objects.create_user("b@example.com", password="x" * 12, name="B")) is None

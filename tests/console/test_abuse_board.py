"""Unit under test: `console.services.abuse` (`AbuseBoard`, `ChallengeSwitch`) behind `GET /api/console/abuse` and
`GET/PUT /api/console/auth-settings`.

Why: the board is how staff notice that someone is farming sign-ups, and the switch is the one lever they have
against it (a challenge visitors must pass). The numbers must be what happened, the board must never name an email,
and the switch must be audited, off until staff turn it on, and unable to be turned on without keys (a challenge
nobody can pass would lock every new person out).

Use cases:
- the board shows 14 days with the accounts made, codes sent, wrong codes, refused throwaway addresses and failed
  challenges the seeded events add up to, the busiest addresses and domains of the last 24 hours, the locked emails and
  the sign-ups waiting; it is read-only and names no email
- the switch reads as off by default, says whether the Turnstile keys are set and which are missing (names only)
- switching it on writes one audit entry with the before and after; switching to the state it is in writes none
- switching on without the keys is refused (`captcha_not_configured`) and writes nothing
- switching it off is allowed without keys, and a missing flag is a 400
"""

from datetime import UTC, datetime, timedelta

import pytest

from accounts.models import AuthEvent, AuthSettings, EmailLock, PendingSignup, SignupRecord, User
from console.models import AuditEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def keys(settings):
    settings.TURNSTILE_SITE_KEY = "site-key-for-the-widget"
    settings.TURNSTILE_SECRET_KEY = "secret-key-never-shown"


def board(client):
    return client.get("/api/console/abuse")


# --- the board ---


def test_the_board_covers_fourteen_days_oldest_first_and_a_quiet_day_is_zeros(staff_client):
    today = datetime.now(UTC).date()

    days = board(staff_client).json()["days"]

    assert len(days) == 14
    assert days[-1]["day"] == today.isoformat() and days[0]["day"] == (today - timedelta(days=13)).isoformat()
    assert all(set(d) == {"day", "accounts_made", "codes_sent", "failed_checks", "disposable_refused",
                          "captcha_failed"} for d in days)  # fmt: skip
    assert all(d["accounts_made"] == d["codes_sent"] == d["failed_checks"] == 0 for d in days)


def test_the_numbers_match_the_events_that_were_seeded(staff_client, user):
    now = datetime.now(UTC)
    SignupRecord.objects.create(user=user, ip="203.0.113.1", email_domain="example.com", method="code")
    for kind, count in (("check_failed", 3), ("disposable_refused", 2), ("captcha_failed", 4)):
        for _ in range(count):
            AuthEvent.objects.create(kind=kind, ip="203.0.113.1", email_domain="mailinator.com")
    AuthEvent.objects.create(kind="check_failed", ip="198.51.100.2", email_domain="")
    old = AuthEvent.objects.create(kind="check_failed", ip="203.0.113.1")
    AuthEvent.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=3))

    body = board(staff_client).json()
    today, three_days_ago = body["days"][-1], body["days"][-4]

    assert (today["accounts_made"], today["failed_checks"]) == (1, 4)
    assert (today["disposable_refused"], today["captcha_failed"]) == (2, 4)
    assert three_days_ago["failed_checks"] == 1
    assert body["top_addresses"][0] == {"name": "203.0.113.1", "count": 10}
    assert body["top_domains"][0] == {"name": "mailinator.com", "count": 9}  # 3 + 2 + 4 events


def test_the_board_counts_locked_emails_and_waiting_sign_ups_and_names_no_email(staff_client, signup):
    now = datetime.now(UTC)
    signup.register(email="secret.person@example.com")
    signup.register(email="gone@example.com")
    PendingSignup.objects.filter(email="gone@example.com").update(expires_at=now - timedelta(minutes=1))
    EmailLock.objects.create(email_canonical="a@example.com", locked_until=now + timedelta(minutes=30), strikes=3)
    EmailLock.objects.create(email_canonical="b@example.com", locked_until=now - timedelta(minutes=30), strikes=3)

    response = board(staff_client)

    assert response.json()["locked_emails"] == 1 and response.json()["waiting_signups"] == 1
    assert "secret.person" not in response.content.decode()


def test_the_board_is_read_only(staff_client):
    assert staff_client.post("/api/console/abuse").status_code == 405
    assert not AuditEntry.objects.exists()


# --- the switch ---


def test_the_switch_is_off_by_default_and_says_which_keys_are_missing(staff_client, settings):
    settings.TURNSTILE_SITE_KEY = ""
    settings.TURNSTILE_SECRET_KEY = ""

    body = staff_client.get("/api/console/auth-settings").json()

    assert body["captcha_enabled"] is False and body["configured"] is False
    assert set(body["missing"]) == {"TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY"}


def test_the_state_never_shows_a_key(staff_client, keys):
    body = staff_client.get("/api/console/auth-settings")

    assert "site-key-for-the-widget" not in body.content.decode()
    assert "secret-key-never-shown" not in body.content.decode()
    assert body.json()["configured"] is True and body.json()["missing"] == []


def test_switching_on_is_audited_with_before_and_after(staff_client, staff_user, keys):
    response = staff_client.put("/api/console/auth-settings", {"captcha_enabled": True}, format="json")

    assert response.status_code == 200 and response.json()["captcha_enabled"] is True
    assert AuthSettings.load().captcha_enabled is True
    (entry,) = AuditEntry.objects.all()
    assert (entry.action, entry.actor_id, entry.target_type) == ("auth_settings.update", staff_user.pk, "auth_settings")
    assert (entry.before, entry.after) == ({"captcha_enabled": False}, {"captcha_enabled": True})


def test_switching_to_the_state_it_is_in_writes_no_entry(staff_client, keys):
    staff_client.put("/api/console/auth-settings", {"captcha_enabled": True}, format="json")
    AuditEntry.objects.all().delete()

    again = staff_client.put("/api/console/auth-settings", {"captcha_enabled": True}, format="json")
    off_already = AuthSettings.objects.filter(pk=1).update(captcha_enabled=False)
    still_off = staff_client.put("/api/console/auth-settings", {"captcha_enabled": False}, format="json")

    assert again.status_code == 200 and still_off.status_code == 200 and off_already == 1
    assert not AuditEntry.objects.exists()


def test_switching_on_without_the_keys_is_refused_and_writes_nothing(staff_client, settings):
    settings.TURNSTILE_SITE_KEY = "only-the-site-key"
    settings.TURNSTILE_SECRET_KEY = ""

    response = staff_client.put("/api/console/auth-settings", {"captcha_enabled": True}, format="json")

    assert (response.status_code, response.json()["code"]) == (409, "captcha_not_configured")
    assert AuthSettings.load().captcha_enabled is False and not AuditEntry.objects.exists()


def test_switching_off_needs_no_keys(staff_client, settings, staff_user):
    AuthSettings.objects.update_or_create(pk=1, defaults={"captcha_enabled": True})
    settings.TURNSTILE_SITE_KEY = settings.TURNSTILE_SECRET_KEY = ""

    response = staff_client.put("/api/console/auth-settings", {"captcha_enabled": False}, format="json")

    assert response.status_code == 200 and AuthSettings.load().captcha_enabled is False
    assert AuditEntry.objects.get().before == {"captcha_enabled": True}


def test_a_request_without_the_flag_is_a_400_and_changes_nothing(staff_client, keys):
    response = staff_client.put("/api/console/auth-settings", {}, format="json")

    assert response.status_code == 400 and not AuditEntry.objects.exists()


def test_a_learner_cannot_read_or_change_the_switch(learner_client, keys):
    assert learner_client.get("/api/console/auth-settings").status_code == 404
    assert learner_client.put("/api/console/auth-settings", {"captcha_enabled": True}, format="json").status_code == 404
    assert not User.objects.filter(is_staff=True).exists()
    assert AuthSettings.load().captcha_enabled is False

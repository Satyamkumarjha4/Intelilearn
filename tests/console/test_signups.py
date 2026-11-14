"""Unit under test: `console.services.signups.PendingSignups` behind `GET /api/console/signups` and its actions
(`resend`, `unlock`, `approve`).

Why: a person who registered but never got (or lost) their code is not an account yet, so nothing else in the console
can see them. Staff need to find them and help. The one powerful action, approve, makes an account for someone nobody
has proved, so it must carry no password (the one the person typed is never copied: whoever typed it may not own the
inbox), tell staff to confirm the person out of band first, need a typed reason, and give the signup credits once.

Use cases:
- the list shows the people waiting (not those whose sign-up expired), newest first, searchable by email, with how many
  tries the live code has used and whether the email is locked; never a code, a hash or a password
- resend sends a new code to the address given at sign-up, cancels the old one, is audited without the email address
  (its domain only) and says it works only in the browser that registered; an expired or unknown sign-up is refused
- unlock clears the lock and the live code, audited; with nothing to unlock it is refused (`not_locked`)
- approve needs a typed reason, makes the account with an unusable password (the pending row's hash is nowhere on the
  user), verified by staff, with the signup record and credits once, deletes the pending row, and replies that the
  person signs in with Google or by a reset and that staff must confirm them out of band
- the approved account can then be reset into a first password (a reset by code works for a password-less account)
- approve is refused for an expired sign-up, for an email that has an account, and without a reason; it writes no entry
- the change log never holds the email address of a sign-up
"""

from datetime import timedelta

import pytest
from rest_framework.throttling import SimpleRateThrottle

from accounts.models import EmailLock, PendingSignup, SignupRecord, User, VerificationCode
from accounts.verification.locks import EmailLocks
from console.models import AuditEntry
from credits.models import CreditTransaction

pytestmark = pytest.mark.django_db

REASON = "Spoke to the student's teacher at the school"
EMAIL = "waiting@example.com"


@pytest.fixture
def loose_limits(monkeypatch):
    """The code limits are tested on their own; here a reset right after a sign-up must not be held by the cooldown."""
    for scope in ("auth_code_cooldown", "auth_code_send_email", "auth_code_send_ip", "auth_code_check_email"):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, "1000/min")


@pytest.fixture
def waiting(signup, mailbox):
    """Registered through the real endpoint and not yet entered the code: a pending row and its mailed code."""
    assert signup.register(email=EMAIL, name="Wanda Waiting").status_code == 202
    return PendingSignup.objects.get(email=EMAIL)


def post(client, pending, action, body=None, capture=None):
    url = f"/api/console/signups/{pending.pk}/{action}"

    def send():
        return client.post(url, body, format="json") if body is not None else client.post(url)

    if capture is None:
        return send()
    with capture(execute=True):
        return send()


def grants(user):
    return CreditTransaction.objects.filter(idempotency_key=f"signup:{user.pk}").count()


# --- the list ---


def test_the_list_shows_who_is_waiting_with_their_code_and_lock_and_never_a_secret(staff_client, waiting, mailbox):
    for _ in range(3):
        EmailLocks().strike(waiting.email_canonical)
    VerificationCode.objects.filter(pending=waiting).update(attempts=2)

    response = staff_client.get("/api/console/signups")

    (row,) = response.json()["results"]
    assert (row["id"], row["email"], row["name"]) == (str(waiting.pk), EMAIL, "Wanda Waiting")
    assert (row["code_tries"], row["code_max_tries"]) == (2, 5) and row["locked_until"]
    assert set(row) == {"id", "email", "name", "created_at", "expires_at", "code_tries", "code_max_tries",
                        "code_expires_at", "locked_until"}  # fmt: skip
    text = response.content.decode()
    assert waiting.password_hash not in text and mailbox.code_for(EMAIL) not in text


def test_the_list_leaves_out_expired_sign_ups_and_can_be_searched_newest_first(staff_client, signup, now):
    for name in ("one", "two", "three"):
        signup.register(email=f"{name}@example.com")
    PendingSignup.objects.filter(email="one@example.com").update(created_at=now - timedelta(hours=3))
    PendingSignup.objects.filter(email="two@example.com").update(created_at=now - timedelta(hours=1))
    PendingSignup.objects.filter(email="three@example.com").update(expires_at=now - timedelta(minutes=1))

    emails = [r["email"] for r in staff_client.get("/api/console/signups").json()["results"]]
    found = [r["email"] for r in staff_client.get("/api/console/signups?q=ONE").json()["results"]]

    assert emails == ["two@example.com", "one@example.com"] and found == ["one@example.com"]


def test_the_list_runs_the_same_number_of_queries_for_two_rows_and_for_ten(staff_client, signup, count_queries):
    signup.register(email="a@example.com")
    signup.register(email="b@example.com")
    small = count_queries(lambda: staff_client.get("/api/console/signups"))
    for n in range(8):
        signup.register(email=f"more{n}@example.com")

    assert count_queries(lambda: staff_client.get("/api/console/signups")) == small


# --- resend ---


def test_resend_sends_a_new_code_to_the_address_given_and_audits_it_without_the_email(
    staff_client, staff_user, waiting, mailbox, django_capture_on_commit_callbacks
):
    old = VerificationCode.objects.get(pending=waiting, consumed_at=None, invalidated_at=None)

    response = post(staff_client, waiting, "resend", capture=django_capture_on_commit_callbacks)

    assert response.status_code == 200 and response.json()["sent"] is True
    assert "same browser" in response.json()["note"] or "browser that made" in response.json()["note"]
    old.refresh_from_db()
    assert old.invalidated_at is not None
    assert len(mailbox.to(EMAIL, "signup_code")) == 2
    (entry,) = AuditEntry.objects.all()
    assert (entry.action, entry.actor_id, entry.target_type, entry.target_id) == (
        "signup.resend", staff_user.pk, "signup", str(waiting.pk))  # fmt: skip
    assert EMAIL not in str(entry.before) + str(entry.after) and entry.before == {"email_domain": "example.com"}


def test_resend_is_refused_for_an_expired_or_unknown_sign_up(staff_client, waiting, now):
    PendingSignup.objects.filter(pk=waiting.pk).update(expires_at=now - timedelta(minutes=1))

    expired = post(staff_client, waiting, "resend")
    unknown = staff_client.post("/api/console/signups/00000000-0000-0000-0000-000000000000/resend")

    assert (expired.status_code, expired.json()["code"]) == (409, "expired") and unknown.status_code == 404
    assert not AuditEntry.objects.exists()


# --- unlock ---


def test_unlock_clears_the_lock_and_the_live_code_and_is_audited(staff_client, staff_user, waiting):
    for _ in range(3):
        EmailLocks().strike(waiting.email_canonical)

    response = post(staff_client, waiting, "unlock")

    assert response.status_code == 200 and response.json()["unlocked"] is True
    assert not EmailLock.objects.exists()
    assert not VerificationCode.objects.filter(pending=waiting, consumed_at=None, invalidated_at=None).exists()
    (entry,) = AuditEntry.objects.all()
    assert (entry.action, entry.actor_id) == ("signup.unlock", staff_user.pk)
    assert entry.before["locked"] is True and EMAIL not in str(entry.before)


def test_unlock_is_refused_when_there_is_nothing_to_unlock(staff_client, waiting):
    VerificationCode.objects.filter(pending=waiting).update(invalidated_at="2026-01-01T00:00:00Z")

    response = post(staff_client, waiting, "unlock")

    assert (response.status_code, response.json()["code"]) == (409, "not_locked")
    assert not AuditEntry.objects.exists()


# --- approve ---


def test_approve_makes_an_account_with_no_usable_password_and_credits_it_once(
    staff_client, staff_user, waiting, django_capture_on_commit_callbacks
):
    typed_hash = waiting.password_hash

    response = post(staff_client, waiting, "approve", {"reason": REASON}, django_capture_on_commit_callbacks)

    assert response.status_code == 200
    user = User.objects.get(email=EMAIL)
    body = response.json()
    assert body["learner_id"] == str(user.pk) and body["signs_in_with"] == "google_or_reset"
    assert "out of band" in body["note"] and "Google" in body["note"] and "Forgot password" in body["note"]
    assert not user.has_usable_password() and typed_hash not in (user.password, "") and user.password != typed_hash
    assert user.is_email_verified and user.email_verification_source == "staff"
    assert user.name == "Wanda Waiting" and user.is_active and not user.is_staff
    assert not PendingSignup.objects.exists() and grants(user) == 1
    assert SignupRecord.objects.get(user=user).method == "staff"


def test_approve_is_audited_with_the_actor_and_reason_and_never_the_email(staff_client, staff_user, waiting):
    post(staff_client, waiting, "approve", {"reason": REASON})

    (entry,) = AuditEntry.objects.all()
    assert (entry.action, entry.actor_id, entry.target_type) == ("signup.approved", staff_user.pk, "signup")
    assert entry.after["reason"] == REASON and entry.after["source"] == "staff"
    assert entry.before == {"email_domain": "example.com"} and EMAIL not in str(entry.before) + str(entry.after)


def test_the_approved_person_cannot_sign_in_with_what_they_typed_but_can_choose_a_password_by_reset(
    staff_client, waiting, api_client, loose_limits, mailbox, django_capture_on_commit_callbacks
):
    post(staff_client, waiting, "approve", {"reason": REASON}, django_capture_on_commit_callbacks)

    typed = api_client.post(
        "/api/auth/login", {"email": EMAIL, "password": "correct-horse-battery-staple"}, format="json"
    )
    with django_capture_on_commit_callbacks(execute=True):
        api_client.post("/api/auth/password/forgot", {"email": EMAIL}, format="json")
    code = mailbox.code_for(EMAIL, "reset_code")
    reset = api_client.post(
        "/api/auth/password/reset",
        {"email": EMAIL, "code": code, "new_password": "a-brand-new-passphrase-9"},
        format="json",
    )

    assert typed.status_code == 401
    assert reset.status_code == 200, reset.content
    assert User.objects.get(email=EMAIL).has_usable_password()


@pytest.mark.parametrize("body", [None, {}, {"reason": "short"}, {"reason": "         "}])
def test_approve_needs_a_typed_reason_and_changes_nothing_without_one(staff_client, waiting, body):
    response = post(staff_client, waiting, "approve", body)

    assert response.status_code == 400
    assert PendingSignup.objects.filter(pk=waiting.pk).exists() and not User.objects.filter(email=EMAIL).exists()
    assert not AuditEntry.objects.exists()


def test_pressing_approve_twice_makes_one_account_and_one_grant(
    staff_client, waiting, django_capture_on_commit_callbacks
):
    post(staff_client, waiting, "approve", {"reason": REASON}, django_capture_on_commit_callbacks)

    again = post(staff_client, waiting, "approve", {"reason": REASON}, django_capture_on_commit_callbacks)

    assert again.status_code == 404  # the pending row went with the first approval
    assert User.objects.filter(email=EMAIL).count() == 1
    assert CreditTransaction.objects.filter(idempotency_key__startswith="signup:").count() == 1
    assert AuditEntry.objects.count() == 1


def test_approve_is_refused_for_an_expired_sign_up_and_for_an_email_that_has_an_account(
    staff_client, waiting, now, user
):
    PendingSignup.objects.filter(pk=waiting.pk).update(expires_at=now - timedelta(minutes=1))
    expired = post(staff_client, waiting, "approve", {"reason": REASON})
    PendingSignup.objects.filter(pk=waiting.pk).update(
        expires_at=now + timedelta(hours=1), email=user.email, email_canonical=user.email_canonical + ".x"
    )
    taken = post(staff_client, waiting, "approve", {"reason": REASON})

    assert (expired.status_code, expired.json()["code"]) == (409, "expired")
    assert (taken.status_code, taken.json()["code"]) == (409, "account_exists")
    assert not AuditEntry.objects.exists() and User.objects.filter(email=user.email).count() == 1

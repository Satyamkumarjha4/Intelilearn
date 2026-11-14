"""Unit under test: `console.services.learner_verification.LearnerVerification` behind
`GET /api/console/learners/{id}/verification` and its three actions (`resend`, `unlock`, `mark-verified`).

Why: the first thing a person who cannot sign in does is write to support. Staff need to see why (was the email ever
proved, which codes were sent and what happened to them, is the address locked) and to fix it without a developer. The
panel must never show a code or a hash, every action must be audited with who did it, `mark-verified` vouches for a
person nobody has proved, so it needs a typed reason and may give the signup credits only once, and each action
must refuse the account it makes no sense for rather than quietly doing nothing.

Use cases:
- the panel says whether and how the email was verified, how the person can sign in (a password, each linked provider),
  the last codes (state, tries; never the code or its hash), the last mails, the lock, and the signup record
- an unverified account can be sent a new code: it goes to the learner's own address, the old one is cancelled, one
  audit entry; a verified, closed or erased account is refused with its own code and writes no entry
- unlock lets a locked email check codes again: the lock and the live codes are cleared, one audit entry; with nothing
  to unlock it is refused (`nothing_to_unlock`)
- mark-verified needs a typed reason of at least 10 characters, verifies the account with the source `staff`, grants
  the signup credits exactly once (a second press is refused, the first verified it), and keeps the reason in the
  change log
- a stranger's id is a 404, and the panel reads without writing
"""

import pytest

from accounts.models import EmailLock, ExternalIdentity, OutboundMail, SignupRecord, User, VerificationCode
from accounts.verification.locks import EmailLocks
from console.models import AuditEntry
from credits.models import CreditTransaction

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"
REASON = "Confirmed by phone with the student's teacher"


@pytest.fixture
def stuck(db):
    """An account whose email was never proved (a legacy or hand-made one)."""
    return User.objects.create_user("stuck@example.com", password=PASSWORD, name="Stuck Student")


def panel(client, learner):
    return client.get(f"/api/console/learners/{learner.pk}/verification")


def act(client, learner, action, body=None, capture=None):
    url = f"/api/console/learners/{learner.pk}/verification/{action}"
    if capture is None:
        return client.post(url, body, format="json") if body is not None else client.post(url)
    with capture(execute=True):
        return client.post(url, body, format="json") if body is not None else client.post(url)


def entries():
    return list(AuditEntry.objects.order_by("id"))


def grants(learner):
    return CreditTransaction.objects.filter(idempotency_key=f"signup:{learner.pk}").count()


# --- the panel ---


def test_the_panel_says_how_the_email_was_verified_and_how_the_person_can_sign_in(staff_client, user):
    ExternalIdentity.objects.create(user=user, provider="google", subject="g-1", email_at_link=user.email)

    body = panel(staff_client, user).json()

    assert body["learner"] == {"id": str(user.pk), "name": user.name, "email": user.email}
    assert body["state"]["verified"] is True and body["state"]["source"] == user.email_verification_source
    assert body["state"]["can_resend"] is False and body["state"]["can_mark_verified"] is False
    assert body["sign_in_methods"] == ["password", "google"]
    assert [i["provider"] for i in body["identities"]] == ["google"]


def test_a_password_less_account_does_not_list_a_password(staff_client, user):
    user.set_unusable_password()
    user.save()

    assert panel(staff_client, user).json()["sign_in_methods"] == []


def test_the_panel_lists_the_last_codes_mails_lock_and_signup_record_without_any_code(
    staff_client, stuck, signup, mailbox, django_capture_on_commit_callbacks, now
):
    signup.login(stuck.email, PASSWORD)  # an unverified account's sign-in mails it a login code
    code = mailbox.code_for(stuck.email, "login_code")
    for _ in range(3):
        EmailLocks().strike(stuck.email_canonical)
    SignupRecord.objects.create(user=stuck, ip="203.0.113.9", email_domain="example.com", method="code")

    response = panel(staff_client, stuck)
    body = response.json()

    assert body["state"] == {
        "verified": False, "verified_at": None, "source": "", "legacy": False, "closed": False, "erased": False,
        "can_resend": True, "can_mark_verified": True, "can_unlock": True,
    }  # fmt: skip
    assert [(c["purpose"], c["state"], c["tries"]) for c in body["codes"]] == [("login", "live", 0)]
    assert [(m["kind"], m["status"]) for m in body["mail"]] == [("login_code", OutboundMail.objects.get().status)]
    assert body["lock"]["strikes"] == 3 and body["lock"]["locked_until"]
    assert body["signup_record"]["email_domain"] == "example.com" and body["signup_record"]["ip"] == "203.0.113.9"
    stored_hash = VerificationCode.objects.get().code_hash
    assert code not in response.content.decode() and stored_hash not in response.content.decode()
    assert "code_hash" not in response.content.decode()


def test_a_code_is_shown_as_used_cancelled_dead_or_expired(staff_client, stuck, now):
    from datetime import timedelta

    def make(**fields):
        base = {"purpose": "login", "email_canonical": stuck.email_canonical, "user": stuck, "code_hash": "x" * 64,
                "max_attempts": 5, "expires_at": now + timedelta(minutes=10)}  # fmt: skip
        return VerificationCode.objects.create(**base | fields)

    make(consumed_at=now)
    make(invalidated_at=now)
    make(invalidated_at=now, attempts=5)
    make(expires_at=now - timedelta(minutes=1))

    states = [c["state"] for c in panel(staff_client, stuck).json()["codes"]]

    assert sorted(states) == ["cancelled", "dead", "expired", "used"]


def test_a_stranger_id_is_a_404_and_reading_the_panel_writes_nothing(staff_client, stuck):
    nobody = "00000000-0000-0000-0000-000000000000"

    assert staff_client.get(f"/api/console/learners/{nobody}/verification").status_code == 404

    panel(staff_client, stuck)

    assert not AuditEntry.objects.exists()


# --- resend ---


def test_resend_mails_a_new_code_to_the_learner_cancels_the_old_one_and_is_audited(
    staff_client, staff_user, stuck, signup, mailbox, django_capture_on_commit_callbacks
):
    signup.login(stuck.email, PASSWORD)
    first = VerificationCode.objects.get(consumed_at=None, invalidated_at=None)

    response = act(staff_client, stuck, "resend", capture=django_capture_on_commit_callbacks)

    assert response.status_code == 200 and response.json()["state"]["can_resend"] is True
    first.refresh_from_db()
    assert first.invalidated_at is not None
    assert VerificationCode.objects.filter(consumed_at=None, invalidated_at=None).count() == 1
    assert [m.to for m in mailbox.messages if m.kind == "login_code"] == [stuck.email, stuck.email]
    (entry,) = entries()
    assert (entry.action, entry.actor_id, entry.target_type, entry.target_id) == (
        "learner.verification_resent", staff_user.pk, "learner", str(stuck.pk))  # fmt: skip


@pytest.mark.parametrize(
    ("change", "code"),
    [("verified", "already_verified"), ("closed", "account_closed"), ("erased", "account_erased")],
)
def test_resend_is_refused_for_a_verified_closed_or_erased_account_and_writes_no_entry(
    staff_client, stuck, mailbox, change, code
):
    if change == "verified":
        User.objects.filter(pk=stuck.pk).update(email_verified_at="2026-01-01T00:00:00Z")
    elif change == "closed":
        User.objects.filter(pk=stuck.pk).update(is_active=False)
    else:
        User.objects.filter(pk=stuck.pk).update(is_active=False, deleted_at="2026-01-01T00:00:00Z")

    response = act(staff_client, stuck, "resend")

    assert response.status_code == 409 and response.json()["code"] == code
    assert not AuditEntry.objects.exists() and not mailbox.messages


# --- unlock ---


def test_unlock_clears_the_lock_and_the_live_codes_so_the_email_can_check_again(
    staff_client, staff_user, stuck, signup, mailbox, django_capture_on_commit_callbacks
):
    signup.login(stuck.email, PASSWORD)
    for _ in range(3):
        EmailLocks().strike(stuck.email_canonical)
    assert EmailLocks().is_locked(stuck.email_canonical)

    response = act(staff_client, stuck, "unlock")

    assert response.status_code == 200 and response.json()["lock"] is None
    assert not EmailLocks().is_locked(stuck.email_canonical) and not EmailLock.objects.exists()
    assert not VerificationCode.objects.filter(consumed_at=None, invalidated_at=None).exists()
    act(staff_client, stuck, "resend", capture=django_capture_on_commit_callbacks)
    code = mailbox.code_for(stuck.email, "login_code")
    verified = signup.verify(stuck.email, code, purpose="login")
    assert verified.status_code == 200
    entry = entries()[0]
    assert (entry.action, entry.actor_id) == ("learner.verification_unlocked", staff_user.pk)
    assert entry.before["locked"] is True and entry.after["locked"] is False


def test_unlock_is_refused_when_there_is_nothing_to_unlock(staff_client, stuck):
    response = act(staff_client, stuck, "unlock")

    assert response.status_code == 409 and response.json()["code"] == "nothing_to_unlock"
    assert not AuditEntry.objects.exists()


def test_unlock_is_refused_for_a_closed_account(staff_client, stuck):
    User.objects.filter(pk=stuck.pk).update(is_active=False)
    EmailLocks().strike(stuck.email_canonical)

    response = act(staff_client, stuck, "unlock")

    assert response.status_code == 409 and response.json()["code"] == "account_closed"
    assert EmailLock.objects.exists() and not AuditEntry.objects.exists()


# --- mark verified ---


def test_mark_verified_verifies_by_staff_gives_the_credits_once_and_keeps_the_reason(
    staff_client, staff_user, stuck, django_capture_on_commit_callbacks
):
    response = act(staff_client, stuck, "mark-verified", {"reason": REASON}, django_capture_on_commit_callbacks)

    assert response.status_code == 200
    stuck.refresh_from_db()
    assert stuck.is_email_verified and stuck.email_verification_source == "staff"
    assert response.json()["state"]["verified"] is True and response.json()["state"]["source"] == "staff"
    assert grants(stuck) == 1
    (entry,) = entries()
    assert (entry.action, entry.actor_id) == ("learner.verification_marked", staff_user.pk)
    assert entry.target_id == str(stuck.pk)
    assert entry.before["email_verified"] is False and entry.after["reason"] == REASON
    assert entry.after["source"] == "staff"


def test_pressing_mark_verified_twice_grants_once_and_the_second_is_refused(
    staff_client, stuck, django_capture_on_commit_callbacks
):
    act(staff_client, stuck, "mark-verified", {"reason": REASON}, django_capture_on_commit_callbacks)

    again = act(staff_client, stuck, "mark-verified", {"reason": REASON}, django_capture_on_commit_callbacks)

    assert again.status_code == 409 and again.json()["code"] == "already_verified"
    assert grants(stuck) == 1 and AuditEntry.objects.count() == 1


@pytest.mark.parametrize("body", [None, {}, {"reason": ""}, {"reason": "   "}, {"reason": "too short"}])
def test_mark_verified_needs_a_typed_reason_and_changes_nothing_without_one(
    staff_client, stuck, body, django_capture_on_commit_callbacks
):
    response = act(staff_client, stuck, "mark-verified", body, django_capture_on_commit_callbacks)

    assert response.status_code == 400 and "reason" in response.json().get("fields", response.json())
    stuck.refresh_from_db()
    assert not stuck.is_email_verified and grants(stuck) == 0 and not AuditEntry.objects.exists()


@pytest.mark.parametrize(("change", "code"), [("closed", "account_closed"), ("erased", "account_erased")])
def test_mark_verified_is_refused_for_a_closed_or_erased_account(
    staff_client, stuck, change, code, django_capture_on_commit_callbacks
):
    fields = {"is_active": False} | ({"deleted_at": "2026-01-01T00:00:00Z"} if change == "erased" else {})
    User.objects.filter(pk=stuck.pk).update(**fields)

    response = act(staff_client, stuck, "mark-verified", {"reason": REASON}, django_capture_on_commit_callbacks)

    assert response.status_code == 409 and response.json()["code"] == code
    assert grants(stuck) == 0 and not AuditEntry.objects.exists()

"""Unit under test: `POST /api/auth/password/forgot` and `POST /api/auth/password/reset` (`accounts.views`,
`accounts.verification.reset.PasswordReset`).

Why: a forgotten password is the other door into an account, and it uses the same inbox proof as sign-up, so it must
keep the same promises: the reply never says whether an address has an account, the code works once and dies after
five wrong tries, nothing is sent to a stranger, and a successful reset really locks the old sessions out (a stolen
refresh token must not survive the password change that was meant to end it). Each rule below is a test that fails if
the rule is removed.

Use cases:
- a reset signs the person in with the new password, the old password stops working, and **every older refresh token is
  refused**, on every device, while the new session renews
- a successful reset counts as proof of the inbox: a legacy (or never-verified) account becomes code-verified, and an
  account that was never announced gets its signup credits
- an account with no usable password and no linked sign-in (one staff approved) is mailed a code and the reset sets its
  **first** password
- **a Google-only address gets the "sign in with Google" notice and nothing changes**: no code, the password stays
  unusable, and a reset for it is the plain "no"
- **an unknown address, an address that has only a pending sign-up, a closed account and a known one all get the same
  reply** (status, body, cookies), and nothing is mailed to the first three; the pending sign-up and its code are
  untouched
- **a weak password is refused with field errors** (the same for a known and an unknown address) and spends no try of
  the code
- the code works once, dies after five wrong tries, is not a sign-up or sign-in code, and every failure is `400
  invalid_code`
- **the cooldown, the hourly sends and the check limit hold**, and an unknown address is limited exactly like a known
  one
- an alias of the address finds the account; a malformed address is a field error
"""

import pytest
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from accounts.models import ExternalIdentity, OutboundMail, PendingSignup, User, VerificationCode

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "a-brand-new-passphrase-7"
INVALID = {"detail": "That code didn't work. Check it, or ask for a new one.", "code": "invalid_code"}


@pytest.fixture
def loose_limits(monkeypatch):
    for scope in ("auth_code_cooldown", "auth_code_send_email", "auth_code_send_ip", "auth_code_check_email"):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, "1000/min")


@pytest.fixture
def forgot(api_client, django_capture_on_commit_callbacks):
    def _forgot(email, client=None):
        with django_capture_on_commit_callbacks(execute=True):
            return (client or api_client).post("/api/auth/password/forgot", {"email": email}, format="json")

    return _forgot


@pytest.fixture
def reset(api_client, mailbox, django_capture_on_commit_callbacks):
    def _reset(email, code=None, new_password=NEW_PASSWORD, client=None):
        code = code if code is not None else mailbox.code_for(email, "reset_code")
        body = {"email": email, "code": code, "new_password": new_password}
        with django_capture_on_commit_callbacks(execute=True):
            return (client or api_client).post("/api/auth/password/reset", body, format="json")

    return _reset


def sign_in(email, password=PASSWORD):
    client = APIClient()
    assert client.post("/api/auth/login", {"email": email, "password": password}, format="json").status_code == 200
    return client


# --- the reset itself ---


def test_a_reset_signs_in_with_the_new_password_and_the_old_one_stops_working(forgot, reset, user, api_client):
    assert forgot(user.email).status_code == 202

    reply = reset(user.email)

    assert reply.status_code == 200 and reply.json()["user"]["id"] == str(user.id)
    assert reply.cookies["lc_access"]["httponly"] and reply.cookies["lc_refresh"]["path"] == "/api/auth"
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD) and not user.check_password(PASSWORD)
    assert user.last_login is not None
    assert (
        APIClient().post("/api/auth/login", {"email": user.email, "password": PASSWORD}, format="json").status_code
        == 401
    )
    assert (
        APIClient().post("/api/auth/login", {"email": user.email, "password": NEW_PASSWORD}, format="json").status_code
        == 200
    )


def test_every_older_refresh_token_is_refused_after_a_reset_and_the_new_session_renews(forgot, reset, user):
    phone, laptop = sign_in(user.email), sign_in(user.email)  # two devices, two refresh tokens
    old = [c.cookies["lc_refresh"].value for c in (phone, laptop)]
    forgot(user.email)

    fresh = APIClient()
    reply = reset(user.email, client=fresh)

    assert reply.status_code == 200
    for token in old:
        thief = APIClient()
        thief.cookies["lc_refresh"] = token
        refused = thief.post("/api/auth/refresh")
        assert refused.status_code == 401 and refused.json()["code"] == "session_expired"
    assert fresh.post("/api/auth/refresh").status_code == 200  # the session the reset made is good


def test_a_reset_proves_the_inbox_for_a_legacy_account_and_gives_the_credits_it_never_had(forgot, reset):
    from credits.models import CreditBucket

    legacy = User.objects.create_user(
        "old@example.com", password=PASSWORD, name="Old", email_verified_at="2026-01-01T00:00:00Z",
        email_verification_source="legacy",
    )  # fmt: skip
    forgot("old@example.com")

    assert reset("old@example.com").status_code == 200

    legacy.refresh_from_db()
    assert legacy.email_verification_source == "code" and legacy.email_proved_by_owner
    assert CreditBucket.objects.get(user=legacy).amount_granted == 30


def test_a_reset_verifies_an_account_that_never_proved_its_email(forgot, reset):
    from credits.models import CreditBucket

    stranger = User.objects.create_user("unproved@example.com", password=PASSWORD, name="U")
    forgot("unproved@example.com")

    assert reset("unproved@example.com").status_code == 200

    stranger.refresh_from_db()
    assert stranger.is_email_verified and stranger.email_verification_source == "code"
    assert CreditBucket.objects.filter(user=stranger).count() == 1


def test_an_account_already_proved_by_code_is_left_as_it_was(forgot, reset, user):
    User.objects.filter(pk=user.pk).update(email_verified_at="2026-02-02T00:00:00Z", email_verification_source="code")
    forgot(user.email)

    reset(user.email)

    user.refresh_from_db()
    assert user.email_verified_at.isoformat().startswith("2026-02-02")


def test_a_staff_approved_account_with_no_password_gets_its_first_password_by_a_reset(forgot, reset):
    approved = User.objects.create_user("approved@example.com", password=None, name="Approved", verified=True)
    User.objects.filter(pk=approved.pk).update(email_verification_source="staff")
    assert not approved.has_usable_password()
    forgot("approved@example.com")

    reply = reset("approved@example.com")

    assert reply.status_code == 200
    approved.refresh_from_db()
    assert approved.has_usable_password() and approved.check_password(NEW_PASSWORD)


# --- the Google-only address ---


def test_a_google_only_address_gets_the_notice_and_nothing_changes(forgot, reset, mailbox):
    google = User.objects.create_user("g@example.com", password=None, name="G", verified=True)
    ExternalIdentity.objects.create(user=google, provider="google", subject="sub-1", email_at_link="g@example.com")

    reply = forgot("g@example.com")

    assert reply.status_code == 202
    assert [m.kind for m in mailbox.to("g@example.com")] == ["use_google_notice"]
    assert not VerificationCode.objects.exists()  # no code was made
    google.refresh_from_db()
    assert not google.has_usable_password()
    assert reset("g@example.com", code="123456").json() == INVALID  # and a reset for it is the plain "no"
    google.refresh_from_db()
    assert not google.has_usable_password()


def test_an_account_with_google_and_a_password_gets_a_code_like_any_other(forgot, mailbox, user):
    ExternalIdentity.objects.create(user=user, provider="google", subject="sub-2", email_at_link=user.email)

    forgot(user.email)

    assert [m.kind for m in mailbox.to(user.email)] == ["reset_code"]


# --- the same reply for everyone ---


def test_unknown_pending_only_closed_and_known_addresses_get_the_same_reply(
    forgot, mailbox, user, signup, loose_limits
):
    signup.register(email="waiting@example.com")  # a pending sign-up: no account yet
    waiting_code = signup.code("waiting@example.com")
    mails_before = len(mailbox.messages)
    closed = User.objects.create_user("closed@example.com", password=PASSWORD, name="C", verified=True)
    User.objects.filter(pk=closed.pk).update(is_active=False)

    replies = {e: forgot(e) for e in ("nobody@example.com", "waiting@example.com", closed.email, user.email)}

    assert {r.status_code for r in replies.values()} == {202}
    assert len({r.content for r in replies.values()}) == 1 and replies["nobody@example.com"].json() == {
        "status": "sent"
    }
    assert len({tuple(sorted(r.cookies)) for r in replies.values()}) == 1
    sent = mailbox.messages[mails_before:]
    assert [(m.kind, m.to) for m in sent] == [("reset_code", user.email)]  # nothing for the other three
    assert PendingSignup.objects.filter(email_canonical="waiting@example.com").count() == 1
    live = VerificationCode.objects.get(email_canonical="waiting@example.com", invalidated_at=None)
    assert (live.purpose, live.attempts) == ("signup", 0)
    assert signup.verify("waiting@example.com", waiting_code).status_code == 200  # the pending code still works


def test_a_reset_for_a_pending_only_address_is_the_plain_no_and_creates_nothing(signup, reset, loose_limits):
    signup.register(email="waiting@example.com")
    signup_code = signup.code("waiting@example.com")

    reply = reset("waiting@example.com", code=signup_code)  # the sign-up code, offered to the reset

    assert reply.status_code == 400 and reply.json() == INVALID
    assert not User.objects.filter(email_canonical="waiting@example.com").exists()
    assert VerificationCode.objects.get(purpose="signup").attempts == 0  # and it spent none of the sign-up's tries


def test_a_closed_account_is_sent_nothing_and_a_reset_for_it_is_the_plain_no(forgot, reset, mailbox, user):
    User.objects.filter(pk=user.pk).update(is_active=False)

    assert forgot(user.email).status_code == 202

    assert mailbox.messages == [] and reset(user.email, code="123456").json() == INVALID


def test_an_alias_of_the_address_finds_the_account_and_a_malformed_address_is_a_field_error(forgot, mailbox, user):
    assert forgot("ADA+maths@example.com").status_code == 202
    assert [m.to for m in mailbox.messages] == [user.email]  # mailed to the address the account has

    bad = forgot("not an address")
    assert bad.status_code == 400 and "email" in bad.json()["fields"]


# --- the password ---


def test_a_weak_password_is_refused_with_field_errors_and_spends_no_try(forgot, reset, user, loose_limits):
    forgot(user.email)
    code = VerificationCode.objects.get(purpose="reset")

    known = reset(user.email, new_password="12345")
    unknown = reset("nobody@example.com", code="123456", new_password="12345")

    assert known.status_code == unknown.status_code == 400
    assert known.json() == unknown.json() and "new_password" in known.json()["fields"]
    code.refresh_from_db()
    assert code.attempts == 0 and code.consumed_at is None  # the code is still good
    user.refresh_from_db()
    assert user.check_password(PASSWORD)
    assert reset(user.email).status_code == 200  # and a good password with the same code works


def test_the_password_is_judged_against_the_typed_address_not_the_account_so_the_answer_tells_nothing(reset, user):
    """A rule that knew the real name of a real account would tell whether the account exists."""
    user_name_as_password = user.name.replace(" ", "").lower() + "99"

    known = reset(user.email, code="123456", new_password=user_name_as_password)
    unknown = reset("nobody@example.com", code="123456", new_password=user_name_as_password)

    assert known.status_code == unknown.status_code and known.json() == unknown.json()


# --- the code ---


def test_the_code_works_once_and_every_failure_is_the_same_invalid_code(forgot, reset, user, mailbox, loose_limits):
    forgot(user.email)
    code = mailbox.code_for(user.email, "reset_code")
    wrong = "000000" if code != "000000" else "111111"

    assert reset(user.email, code=wrong).json() == INVALID
    assert reset("nobody@example.com", code=wrong).json() == INVALID
    assert reset(user.email, code=code).status_code == 200
    assert reset(user.email, code=code, new_password="another-good-one-8").json() == INVALID  # used
    forgot(user.email)
    VerificationCode.objects.filter(purpose="reset", invalidated_at=None).update(expires_at="2000-01-01T00:00:00Z")
    assert reset(user.email).json() == INVALID  # expired


def test_five_wrong_tries_kill_the_code_even_for_the_right_one(forgot, reset, user, mailbox, loose_limits):
    forgot(user.email)
    code = mailbox.code_for(user.email, "reset_code")

    for _ in range(5):
        assert reset(user.email, code="000000" if code != "000000" else "111111").status_code == 400

    assert reset(user.email, code=code).json() == INVALID
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_a_reset_code_is_not_a_sign_up_or_sign_in_code_and_the_reverse(forgot, signup, user, mailbox, loose_limits):
    stranger = User.objects.create_user("unproved@example.com", password=PASSWORD, name="U")
    forgot(stranger.email)
    reset_code = mailbox.code_for(stranger.email, "reset_code")

    assert signup.verify(stranger.email, reset_code, purpose="login").status_code == 400
    assert signup.verify(stranger.email, reset_code, purpose="signup").status_code == 400
    stranger.refresh_from_db()
    assert not stranger.is_email_verified


def test_a_new_forgot_cancels_the_old_code(forgot, reset, user, mailbox, loose_limits):
    forgot(user.email)
    first = mailbox.code_for(user.email, "reset_code")
    forgot(user.email)
    second = mailbox.code_for(user.email, "reset_code")

    if first != second:  # (a one-in-a-million repeat would make the old code the new one)
        assert reset(user.email, code=first).json() == INVALID
    assert reset(user.email, code=second).status_code == 200


# --- the limits ---


def test_the_cooldown_refuses_a_second_forgot_within_a_minute_with_retry_after(forgot, user):
    assert forgot(user.email).status_code == 202

    again = forgot(user.email)

    assert again.status_code == 429 and again.json()["code"] == "throttled" and 0 < int(again["Retry-After"]) <= 60


def test_the_hourly_limit_on_mails_holds_and_an_unknown_address_is_limited_the_same(forgot, user, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth_code_cooldown", "1000/min")
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth_code_send_email", "2/hour")

    known = [forgot(user.email).status_code for _ in range(3)]
    unknown = [forgot("nobody@example.com").status_code for _ in range(3)]

    assert known == unknown == [202, 202, 429]
    assert OutboundMail.objects.filter(to_email=user.email).count() == 2


def test_the_check_limit_stops_guessing_for_a_known_and_an_unknown_address_alike(reset, user, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth_code_check_email", "2/hour")

    known = [reset(user.email, code="000000").status_code for _ in range(3)]
    unknown = [reset("nobody@example.com", code="000000").status_code for _ in range(3)]

    assert known == unknown == [400, 400, 429]


def test_a_malformed_body_is_the_plain_no_for_the_code_and_a_field_error_for_the_password(api_client, loose_limits):
    no_code = api_client.post(
        "/api/auth/password/reset", {"email": "nope", "new_password": NEW_PASSWORD}, format="json"
    )
    no_password = api_client.post(
        "/api/auth/password/reset", {"email": "a@example.com", "code": "123456"}, format="json"
    )

    assert no_code.status_code == 400 and no_code.json() == INVALID
    assert no_password.status_code == 400 and "new_password" in no_password.json()["fields"]


def test_the_reset_endpoints_need_the_csrf_header():
    client = APIClient(enforce_csrf_checks=True)

    assert client.post("/api/auth/password/forgot", {"email": "a@example.com"}, format="json").status_code == 403
    assert client.post("/api/auth/password/reset", {}, format="json").status_code == 403

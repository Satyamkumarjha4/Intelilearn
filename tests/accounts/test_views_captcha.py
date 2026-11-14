"""Unit under test: the sign-up challenge as `POST /api/auth/register` and `POST /api/auth/verify/resend` use it, and
`GET /api/auth/captcha` (`accounts.views`).

Why: when abuse shows up, staff switch a challenge on in the console. From that moment a register or a resend without a
passed challenge must get nowhere (no pending sign-up, no mail, no code made, no throttle spent), and the reply must say
the same whether or not the address has an account. With the switch off, which is the default, nothing may change for
anyone. The challenge is answered by a fake (`support/captcha.py`): a visitor passes with `good-token` only.

Use cases:
- **off by default**: register and resend work with no token and the verifier is never asked
- **with the switch on, register and resend refuse a missing token and a failed one** with the same `400
  captcha_failed`, and nothing is created, mailed or counted against the limits; a good token goes through as usual
- the refusal is the same for an address that has an account and one that does not
- the check comes after the form is validated (a weak password is still a field error) and before the limits and the
  work
- the visitor's address is what the verifier is asked about
- the sign-up screens learn whether to show the widget from `GET /auth/captcha`, which gives the public key only when on
- failed challenges, wrong codes and refused throwaway addresses are written to the abuse board's event log, with the
  address and the email's domain and never the email itself
"""

import pytest
from rest_framework.throttling import SimpleRateThrottle

from accounts.models import AuthEvent, OutboundMail, PendingSignup, VerificationCode

pytestmark = pytest.mark.django_db

REFUSED = {"detail": "Please complete the check and try again.", "code": "captcha_failed"}


@pytest.fixture
def with_token(api_client, django_capture_on_commit_callbacks):
    """POST with an optional `captcha_token` and the visitor's address."""

    def post(path, body, token=None, ip="203.0.113.9"):
        payload = {**body, **({"captcha_token": token} if token is not None else {})}
        with django_capture_on_commit_callbacks(execute=True):
            return api_client.post(path, payload, format="json", HTTP_X_FORWARDED_FOR=ip)

    return post


def new_person(**extra):
    return {
        "name": "Grace",
        "email": "grace.new@example.com",
        "password": "correct-horse-battery-staple",
        "accept_terms": True,
        **extra,
    }


def test_off_by_default_nothing_changes_and_the_verifier_is_never_asked(with_token, settings):
    from support.captcha import FakeVerifier

    settings.CAPTCHA_VERIFIER = "support.captcha.FakeVerifier"
    FakeVerifier.asked.clear()

    register = with_token("/api/auth/register", new_person())
    resend = with_token("/api/auth/verify/resend", {"email": "grace.new@example.com", "purpose": "signup"})

    assert register.status_code == 202 and resend.status_code in (202, 429)
    assert FakeVerifier.asked == [] and not AuthEvent.objects.exists()


def test_the_config_says_off_with_no_key_by_default(api_client):
    assert api_client.get("/api/auth/captcha").json() == {"enabled": False, "site_key": ""}


def test_the_config_gives_the_public_key_only_when_the_challenge_is_on(api_client, captcha_on):
    assert api_client.get("/api/auth/captcha").json() == {"enabled": True, "site_key": "site-key-for-the-widget"}


@pytest.mark.parametrize("token", [None, "", "bad-token"], ids=["missing", "empty", "failed"])
def test_register_refuses_a_missing_or_failed_challenge_and_makes_nothing(with_token, captcha_on, mailbox, token):
    reply = with_token("/api/auth/register", new_person(), token)

    assert reply.status_code == 400 and reply.json() == REFUSED
    assert not PendingSignup.objects.exists() and not VerificationCode.objects.exists()
    assert mailbox.messages == [] and not OutboundMail.objects.exists()
    assert "lc_signup" not in reply.cookies


def test_register_with_a_passed_challenge_goes_through_as_usual(with_token, captcha_on, mailbox):
    reply = with_token("/api/auth/register", new_person(), "good-token")

    assert reply.status_code == 202 and reply.json() == {"status": "verification_required"}
    assert PendingSignup.objects.count() == 1 and [m.kind for m in mailbox.messages] == ["signup_code"]


@pytest.mark.parametrize("token", [None, "bad-token"], ids=["missing", "failed"])
def test_resend_refuses_a_missing_or_failed_challenge_and_sends_nothing(with_token, captcha_on, mailbox, token):
    with_token("/api/auth/register", new_person(), "good-token")
    mails = len(mailbox.messages)

    reply = with_token("/api/auth/verify/resend", {"email": "grace.new@example.com", "purpose": "signup"}, token)

    assert reply.status_code == 400 and reply.json() == REFUSED
    assert len(mailbox.messages) == mails


def test_a_failed_challenge_spends_none_of_the_limits(with_token, captcha_on, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth_code_cooldown", "1/min")

    assert with_token("/api/auth/register", new_person(), "bad-token").status_code == 400
    assert with_token("/api/auth/register", new_person(), None).status_code == 400

    assert with_token("/api/auth/register", new_person(), "good-token").status_code == 202  # not refused for a cooldown


def test_the_refusal_is_the_same_for_an_address_with_an_account_and_one_without(with_token, captcha_on, user):
    known = with_token("/api/auth/register", new_person(email=user.email), "bad-token")
    unknown = with_token("/api/auth/register", new_person(email="nobody@example.com"), "bad-token")

    assert known.status_code == unknown.status_code == 400 and known.json() == unknown.json() == REFUSED


def test_the_form_is_still_checked_first_and_the_visitors_address_is_what_the_verifier_is_asked_about(
    with_token, captcha_on
):
    weak = with_token("/api/auth/register", new_person(password="12345"), "bad-token")
    with_token("/api/auth/register", new_person(), "good-token", ip="198.51.100.77")

    assert weak.status_code == 400 and "password" in weak.json()["fields"]  # a field error, not the challenge
    assert captcha_on.asked == [("good-token", "198.51.100.77")]


def test_failed_challenges_wrong_codes_and_refused_throwaway_addresses_are_counted_without_the_email(
    with_token, captcha_on, signup
):
    with_token("/api/auth/register", new_person(), "bad-token", ip="203.0.113.1")
    with_token("/api/auth/register", new_person(email="x@mailinator.com"), "good-token", ip="203.0.113.2")
    with_token("/api/auth/register", new_person(), "good-token", ip="203.0.113.3")
    with_token(
        "/api/auth/verify", {"email": "grace.new@example.com", "code": "000000", "purpose": "signup"}, ip="203.0.113.4"
    )

    events = {(e.kind, e.ip, e.email_domain) for e in AuthEvent.objects.all()}
    assert events == {
        ("captcha_failed", "203.0.113.1", ""),
        ("disposable_refused", "203.0.113.2", "mailinator.com"),
        ("check_failed", "203.0.113.4", "example.com"),
    }
    assert "grace.new" not in str(list(AuthEvent.objects.values()))  # never the address, only its domain


def test_a_wrong_reset_code_is_counted_too(with_token, user):
    from accounts.models import User

    User.objects.filter(pk=user.pk).update(is_active=True)
    reply = with_token(
        "/api/auth/password/reset",
        {"email": user.email, "code": "000000", "new_password": "a-brand-new-passphrase-7"},
        ip="203.0.113.8",
    )

    assert reply.status_code == 400
    assert AuthEvent.objects.get().kind == "check_failed" and AuthEvent.objects.get().ip == "203.0.113.8"


def test_a_counter_that_cannot_be_written_never_stops_the_request(with_token, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the event log is down")

    monkeypatch.setattr(AuthEvent.objects, "create", broken)

    reply = with_token("/api/auth/register", new_person(email="x@mailinator.com"))

    assert reply.status_code == 400 and "email" in reply.json()["fields"]  # the refusal still reaches the person

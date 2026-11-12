"""Unit under test: the sign-in-with-a-provider endpoints (`accounts.views`: `GET /auth/providers`,
`/auth/oauth/<provider>/start`, `/auth/oauth/<provider>/callback`, `GET` and `POST /auth/oauth/finish`) with the
stand-in provider, and the `OAuthSignIn` facade behind them.

Why: this is the second way into an account, and it must keep the promises the email-and-code way keeps. A new person
has NO account and NO credits until they take the last step; an address that is already ours is linked only when its
owner proved it, and otherwise taken over by whoever has just proved it (so an old password and old sessions stop
working); an address the provider does not call verified, a staff account and a closed one are refused; a forged or
replayed callback and a `next` that leads off the site go nowhere. The stand-in answers the redirect itself, so the
real state check, linking policy and cookies all run.

Use cases:
- the provider list shows only what is on, and the stand-in is off unless its own switch is on
- start redirects with the signed `lc_oauth` cookie (httpOnly, `SameSite=Lax`, scoped to the sign-in path); a provider
  that is off redirects to `provider_off` and sets no cookie
- **a new person has no account and no credits after the callback**, only a `lc_finish` ticket; the form needs the
  terms and a name; the last step makes the account (no password, verified by the provider, terms stamped, identity
  linked, time zone applied) and gives **exactly 30 credits**, once
- the last step with no, forged or expired ticket is `finish_expired` (a `404` for the form's own read)
- an account whose email was proved by a code is linked to and signed in, with **no second account and no second
  grant**, and its password still works; signing in again by the link adds nothing
- **a never-verified or legacy account is taken over: its old password and its old refresh token fail**, it is
  verified by the provider and gets its credits once
- an unverified Google email, a staff account, a closed account and an address linked to a different Google person
  are each refused with their code and change nothing
- a wrong, missing or replayed state is `state_mismatch`; the `lc_oauth` cookie is cleared after every callback
- `next` goes through `RedirectPolicy`: an off-site value is dropped at the start, and a good one survives to the
  sign-in page
- the sign-in endpoints are rate limited per address
- the last step's POST needs the CSRF header
"""

import json

import pytest
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import ExternalIdentity, PendingSignup, SignupRecord, User
from credits.models import CreditBucket, CreditTransaction

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"
PERSON = {"subject": "sub-ada", "email": "Ada@Example.com", "name": "Ada Lovelace"}


def location(response):
    return response["Location"]


def grants(user):
    return CreditTransaction.objects.filter(user=user, idempotency_key=f"signup:{user.pk}").count()


def finish(client, capture, body=None, **extra):
    with capture(execute=True):
        return client.post(
            "/api/auth/oauth/finish",
            {"name": "Ada L", "accept_terms": True, **(body or {})},
            format="json",
            **extra,
        )


# --- the list and the start ---


def test_the_provider_list_shows_only_what_is_on(api_client, fake_google, settings):
    on = api_client.get("/api/auth/providers")

    assert on.status_code == 200 and on.json() == {"providers": [{"key": "fake", "label": "Google (test)"}]}
    settings.AUTH_ALLOW_FAKE_PROVIDER = False  # the stand-in needs its own switch as well as a place in the list
    assert api_client.get("/api/auth/providers").json() == {"providers": []}
    settings.AUTH_PROVIDERS_ENABLED = []
    assert api_client.get("/api/auth/providers").json() == {"providers": []}


def test_start_redirects_with_the_signed_httponly_cookie_scoped_to_the_sign_in_path(oauth):
    reply = oauth.start()

    assert reply.status_code == 302
    assert location(reply).startswith("http://localhost:3000/api/auth/oauth/fake/callback?code=")
    cookie = reply.cookies["lc_oauth"]
    assert cookie["httponly"] and cookie["samesite"] == "Lax" and cookie["path"] == "/api/auth/oauth"
    assert int(cookie["max-age"]) == 10 * 60 and cookie.value


def test_a_provider_that_is_off_redirects_with_provider_off_and_sets_no_cookie(api_client, fake_google, settings):
    settings.AUTH_PROVIDERS_ENABLED = []

    reply = api_client.get("/api/auth/oauth/fake/start")

    assert (
        reply.status_code == 302 and location(reply) == "/auth?error=provider_off" and "lc_oauth" not in reply.cookies
    )
    unknown = api_client.get("/api/auth/oauth/nonesuch/start")
    assert location(unknown) == "/auth?error=provider_off"


def test_a_provider_turned_off_between_the_start_and_the_callback_is_provider_off(oauth, settings):
    started = oauth.start()
    settings.AUTH_PROVIDERS_ENABLED = []

    reply = oauth.callback(started)

    assert location(reply) == "/auth?error=provider_off" and not User.objects.exists()


# --- a new person ---


def test_a_new_person_has_no_account_and_no_credits_until_the_last_step(oauth, api_client):
    reply = oauth.sign_in(PERSON)

    assert reply.status_code == 302 and location(reply) == "/auth/finish"
    assert not User.objects.exists() and not ExternalIdentity.objects.exists()
    assert not CreditBucket.objects.exists() and not CreditTransaction.objects.exists()
    assert not any(name in reply.cookies for name in ("lc_access", "lc_refresh", "lc_session"))
    ticket = reply.cookies["lc_finish"]
    assert ticket["httponly"] and ticket["samesite"] == "Lax" and ticket["path"] == "/api/auth/oauth"
    assert int(ticket["max-age"]) == 15 * 60
    assert api_client.get("/api/auth/oauth/finish").json() == {
        "email": "Ada@Example.com",
        "name": "Ada Lovelace",
    }


def test_the_last_step_makes_the_account_with_exactly_30_credits(oauth, api_client, django_capture_on_commit_callbacks):
    oauth.sign_in(PERSON)

    reply = finish(api_client, django_capture_on_commit_callbacks, {"name": "  Ada L  ", "timezone": "Europe/London"})

    assert reply.status_code == 201 and reply.json()["user"]["email"] == "Ada@example.com"
    user = User.objects.get(email_canonical="ada@example.com")
    assert user.name == "Ada L" and not user.has_usable_password()
    assert (user.email_verification_source, user.is_email_verified) == ("google", True)
    assert user.terms_accepted_at is not None and user.terms_version == User.TERMS_VERSION
    assert user.profile.timezone == "Europe/London"
    link = ExternalIdentity.objects.get(user=user)
    assert (link.provider, link.subject, link.email_at_link) == ("fake", "sub-ada", "Ada@Example.com")
    assert SignupRecord.objects.get(user=user).method == "google"
    bucket = CreditBucket.objects.get(user=user)
    assert (bucket.source, bucket.amount_granted) == ("signup", 30) and grants(user) == 1
    for name in ("lc_access", "lc_refresh", "lc_session"):
        assert reply.cookies[name].value
    assert reply.cookies["lc_finish"]["max-age"] == 0  # the ticket is spent


def test_the_last_step_needs_the_terms_and_a_name_and_creates_nothing_without_them(
    oauth, api_client, django_capture_on_commit_callbacks
):
    oauth.sign_in(PERSON)

    no_terms = finish(api_client, django_capture_on_commit_callbacks, {"accept_terms": False})
    no_name = finish(api_client, django_capture_on_commit_callbacks, {"name": "   "})
    missing = finish(api_client, django_capture_on_commit_callbacks, {"accept_terms": None})

    assert no_terms.status_code == no_name.status_code == missing.status_code == 400
    assert no_terms.json()["fields"] == {"accept_terms": ["Please confirm to continue."]}
    assert no_name.json()["fields"] == {"name": ["Tell us your name."]}
    assert not User.objects.exists() and not CreditBucket.objects.exists()
    assert api_client.get("/api/auth/oauth/finish").status_code == 200  # the ticket is still there for another try


def test_the_last_step_with_no_forged_or_expired_ticket_is_finish_expired(
    api_client, oauth, django_capture_on_commit_callbacks, monkeypatch
):
    assert api_client.get("/api/auth/oauth/finish").status_code == 404
    none = finish(api_client, django_capture_on_commit_callbacks)
    assert none.status_code == 400 and none.json()["code"] == "finish_expired"

    api_client.cookies["lc_finish"] = "forged-ticket"
    assert api_client.get("/api/auth/oauth/finish").status_code == 404
    assert finish(api_client, django_capture_on_commit_callbacks).json()["code"] == "finish_expired"

    import time

    oauth.sign_in(PERSON)
    later = time.time() + 16 * 60
    monkeypatch.setattr("django.core.signing.time.time", lambda: later)
    assert finish(api_client, django_capture_on_commit_callbacks).json()["code"] == "finish_expired"
    assert not User.objects.exists()


def test_the_last_step_deletes_a_pending_sign_up_for_the_same_address(
    oauth, api_client, signup, django_capture_on_commit_callbacks
):
    signup.register(email="ada@example.com")  # someone started a sign-up by code for the same inbox
    assert PendingSignup.objects.count() == 1

    oauth.sign_in(PERSON)
    finish(api_client, django_capture_on_commit_callbacks)

    assert not PendingSignup.objects.exists() and User.objects.count() == 1


def test_a_second_finish_for_the_same_person_signs_the_same_account_in_and_makes_no_second_one(
    oauth, django_capture_on_commit_callbacks
):
    from support.oauth import OAuthFlow

    here, there = APIClient(), APIClient()  # the same person starts in two browsers before finishing in either
    OAuthFlow(here, django_capture_on_commit_callbacks).sign_in(PERSON)
    OAuthFlow(there, django_capture_on_commit_callbacks).sign_in(PERSON)

    first = finish(here, django_capture_on_commit_callbacks)
    second = finish(there, django_capture_on_commit_callbacks)

    assert first.status_code == second.status_code == 201
    assert first.json()["user"]["id"] == second.json()["user"]["id"]
    assert User.objects.count() == ExternalIdentity.objects.count() == CreditBucket.objects.count() == 1


# --- an existing account ---


def test_an_account_whose_email_was_proved_by_a_code_is_linked_with_no_second_account_or_grant(oauth, signup):
    signup.complete(email="ada@example.com")
    user = User.objects.get(email_canonical="ada@example.com")
    assert grants(user) == 1

    reply = oauth.sign_in({**PERSON, "email": "Ada+x@Example.com"})  # an alias of the same inbox

    assert reply.status_code == 302 and location(reply) == "/auth"
    assert reply.cookies["lc_access"].value and reply.cookies["lc_refresh"].value and reply.cookies["lc_session"].value
    assert User.objects.count() == 1 and ExternalIdentity.objects.get().user == user
    assert grants(user) == 1 and CreditBucket.objects.count() == 1
    user.refresh_from_db()
    assert user.check_password("correct-horse-battery-staple")  # linking changes no password
    assert user.email_verification_source == "code"


def test_signing_in_again_through_the_link_adds_nothing(oauth, user):
    User.objects.filter(pk=user.pk).update(email_verified_at="2026-01-01T00:00:00Z", email_verification_source="code")
    oauth.sign_in({"subject": "sub-ada", "email": user.email})
    before = (User.objects.count(), ExternalIdentity.objects.count(), CreditTransaction.objects.count())

    again = oauth.sign_in({"subject": "sub-ada", "email": "a-different-address@example.com"})  # the link is the key

    assert location(again) == "/auth" and again.cookies["lc_access"].value
    assert before == (User.objects.count(), ExternalIdentity.objects.count(), CreditTransaction.objects.count())


@pytest.mark.parametrize("source", ["", "legacy", "staff", "operator"])
def test_an_account_nobody_proved_is_taken_over_its_old_password_and_old_sessions_fail(oauth, source):
    victim = User.objects.create_user("ada@example.com", password=PASSWORD, name="Pre-made")
    if source:
        User.objects.filter(pk=victim.pk).update(
            email_verified_at="2026-01-01T00:00:00Z", email_verification_source=source
        )
    holder = APIClient()  # a session the previous holder of the password has: it renews, so it is live
    holder.cookies["lc_refresh"] = str(RefreshToken.for_user(victim))
    assert holder.post("/api/auth/refresh").status_code == 200
    old_refresh = holder.cookies["lc_refresh"].value  # the rotated token: the one still good before the take-over

    reply = oauth.sign_in(PERSON)

    assert location(reply) == "/auth" and reply.cookies["lc_session"].value
    victim.refresh_from_db()
    assert not victim.has_usable_password()
    assert (victim.email_verification_source, victim.is_email_verified) == ("google", True)
    assert ExternalIdentity.objects.get().user == victim and User.objects.count() == 1
    assert APIClient().post("/api/auth/login", {"email": victim.email, "password": PASSWORD}).status_code == 401
    replay = APIClient()
    replay.cookies["lc_refresh"] = old_refresh
    assert replay.post("/api/auth/refresh").status_code == 401  # the old session is over
    assert grants(victim) == 1  # and the person who proved the inbox gets the credits, once


def test_a_takeover_tells_the_address_the_account_has_and_only_a_takeover_does(oauth, mailbox, signup):
    victim = User.objects.create_user("Ada@example.com", password=PASSWORD, name="Pre-made")

    oauth.sign_in({**PERSON, "email": "ada+typed-differently@example.com"})  # an alias: the notice goes to what the
    # account has, not to what Google said

    sent = [m for m in mailbox.messages if m.kind == "takeover_notice"]
    assert [m.to for m in sent] == ["Ada@example.com"] and victim.email == "Ada@example.com"
    assert "now signs in with Google" in sent[0].text and "old password no longer works" in sent[0].text
    assert "satyamjha4@gmail.com" in sent[0].text  # the contact address of the legal pages (CONTACT_EMAIL)
    before = len(mailbox.messages)
    oauth.sign_in(PERSON)  # signing in again through the link is not a takeover
    assert len(mailbox.messages) == before


def test_no_takeover_notice_for_a_new_person_a_link_or_a_refusal(oauth, mailbox, signup):
    signup.complete(email="linked@example.com")  # an account made by code: it is linked, not taken over
    User.objects.create_user("staff@example.com", password=PASSWORD, name="Staff", is_staff=True)
    mails_before = len(mailbox.messages)

    oauth.sign_in({"subject": "s-new", "email": "brand-new@example.com"})  # a new person
    oauth.sign_in({"subject": "s-link", "email": "linked@example.com"})  # a link
    oauth.sign_in({"subject": "s-staff", "email": "staff@example.com"})  # refused
    oauth.sign_in({"subject": "s-unverified", "email": "x@example.com", "email_verified": False})  # refused

    assert [m for m in mailbox.messages[mails_before:] if m.kind == "takeover_notice"] == []


def test_a_takeover_that_does_not_commit_sends_no_notice(oauth, mailbox, monkeypatch):
    from accounts.verification.activation import AccountActivation

    User.objects.create_user("ada@example.com", password=PASSWORD, name="Pre-made")
    monkeypatch.setattr(
        AccountActivation, "link", lambda self, user, identity: (_ for _ in ()).throw(RuntimeError("x"))
    )

    with pytest.raises(RuntimeError):
        oauth.sign_in(PERSON)

    assert [m for m in mailbox.messages if m.kind == "takeover_notice"] == []
    assert User.objects.get().has_usable_password()  # and the account is as it was


def test_a_second_sign_in_after_a_takeover_adds_no_second_grant(oauth):
    victim = User.objects.create_user("ada@example.com", password=PASSWORD, name="Pre-made")
    oauth.sign_in(PERSON)
    oauth.sign_in(PERSON)

    assert grants(victim) == 1 and ExternalIdentity.objects.count() == 1


# --- refusals ---


def test_an_unverified_google_email_is_refused_and_changes_nothing(oauth, user):
    reply = oauth.sign_in({**PERSON, "email": user.email, "email_verified": False})

    assert location(reply) == "/auth?error=email_not_verified"
    assert not any(name in reply.cookies for name in ("lc_access", "lc_session", "lc_finish"))
    assert not ExternalIdentity.objects.exists() and User.objects.count() == 1
    assert User.objects.get().email_verification_source == "operator"  # untouched


def test_a_staff_account_is_never_linked_or_taken_over(oauth):
    staff = User.objects.create_user("ada@example.com", password=PASSWORD, name="Staff", is_staff=True)

    reply = oauth.sign_in(PERSON)

    assert location(reply) == "/auth?error=sign_in_failed" and "lc_access" not in reply.cookies
    staff.refresh_from_db()
    assert staff.check_password(PASSWORD) and staff.is_staff and not staff.is_email_verified
    assert not ExternalIdentity.objects.exists() and not CreditBucket.objects.exists()


def test_a_closed_account_is_refused(oauth):
    closed = User.objects.create_user("ada@example.com", password=PASSWORD, name="Closed", verified=True)
    User.objects.filter(pk=closed.pk).update(is_active=False)

    reply = oauth.sign_in(PERSON)

    assert location(reply) == "/auth?error=account_closed" and not ExternalIdentity.objects.exists()


def test_an_address_already_linked_to_a_different_google_person_is_not_merged(oauth):
    owner = User.objects.create_user("ada@example.com", password=PASSWORD, name="Owner", verified=True)
    User.objects.filter(pk=owner.pk).update(email_verification_source="google")
    ExternalIdentity.objects.create(user=owner, provider="fake", subject="the-original-person")

    reply = oauth.sign_in({**PERSON, "subject": "a-recycled-address-new-person"})

    assert location(reply) == "/auth?error=sign_in_failed" and "lc_access" not in reply.cookies
    assert ExternalIdentity.objects.count() == 1


# --- the dance itself ---


def test_a_wrong_missing_or_replayed_state_is_state_mismatch_and_the_cookie_is_cleared(oauth):
    started = oauth.start(PERSON)
    wrong = oauth.callback(started, state="not-the-state-we-sent")
    assert location(wrong) == "/auth?error=state_mismatch" and wrong.cookies["lc_oauth"]["max-age"] == 0

    fresh = oauth.start(PERSON)
    replayed_state = oauth.callback(fresh)  # the real one succeeds once...
    assert location(replayed_state) == "/auth/finish"
    again = oauth.callback(fresh)  # ...and the cookie is gone, so the same callback again is nothing
    assert location(again) == "/auth?error=state_mismatch"

    bare = APIClient().get("/api/auth/oauth/fake/callback", {"code": "x", "state": "y"})
    assert location(bare) == "/auth?error=state_mismatch"
    assert not User.objects.exists()


def test_a_callback_for_a_different_provider_than_the_one_started_is_state_mismatch(oauth, settings):
    from accounts.identity.fake import FakeProvider
    from accounts.identity.registry import IdentityProviders

    class Twin(FakeProvider):
        key = "twin"
        display_name = "Twin"

    IdentityProviders.register(Twin)
    try:
        settings.AUTH_PROVIDERS_ENABLED = ["fake", "twin"]
        started = oauth.start(PERSON)  # started with `fake`...
        target = location(started).replace("/fake/callback", "/twin/callback")
        started["Location"] = target  # ...but the callback is addressed to `twin`

        assert location(oauth.callback(started)) == "/auth?error=state_mismatch"
    finally:
        del IdentityProviders.REGISTERED["twin"]


def test_a_person_who_says_no_at_the_provider_is_sign_in_failed(oauth):
    started = oauth.start(PERSON)

    reply = oauth.callback(started, error="access_denied")

    assert location(reply) == "/auth?error=sign_in_failed" and not User.objects.exists()


# --- next ---


def test_next_survives_a_sign_in_and_the_last_step_when_it_is_safe(oauth):
    existing = User.objects.create_user("ada@example.com", password=PASSWORD, name="Ada", verified=True)
    User.objects.filter(pk=existing.pk).update(email_verification_source="code")

    signed_in = oauth.sign_in(PERSON, next="/quizzes/abc?tab=1")
    new_person = oauth.sign_in({"subject": "other", "email": "other@example.com"}, next="/lessons/xyz")

    assert location(signed_in) == "/auth?next=%2Fquizzes%2Fabc%3Ftab%3D1"
    assert location(new_person) == "/auth/finish?next=%2Flessons%2Fxyz"


@pytest.mark.parametrize(
    "evil", ["//evil.com", "https://evil.com", "/\\evil.com", "javascript:alert(1)", "/ok\r\nX: y"]
)
def test_an_off_site_next_is_dropped_at_the_start_so_no_redirect_leaves_the_site(oauth, evil):
    existing = User.objects.create_user("ada@example.com", password=PASSWORD, name="Ada", verified=True)
    User.objects.filter(pk=existing.pk).update(email_verification_source="code")

    ok = oauth.sign_in(PERSON, next=evil)
    refused = oauth.sign_in({**PERSON, "email_verified": False}, next=evil)

    for reply in (ok, refused):
        assert location(reply).startswith("/") and not location(reply).startswith("//")
        assert "evil" not in location(reply)
    assert location(ok) == "/auth"


def test_an_error_keeps_a_safe_next_so_the_person_can_try_again(oauth):
    reply = oauth.sign_in({**PERSON, "email_verified": False}, next="/quizzes")

    assert location(reply) == "/auth?error=email_not_verified&next=%2Fquizzes"


# --- limits and CSRF ---


def test_the_sign_in_endpoints_are_rate_limited_per_address(api_client, fake_google, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth_oauth", "3/min")

    statuses = [
        api_client.get("/api/auth/oauth/fake/start", {"fake": json.dumps(PERSON)}).status_code for _ in range(5)
    ]

    assert statuses == [302, 302, 302, 429, 429]
    assert api_client.get("/api/auth/oauth/finish").status_code == 429


def test_the_last_steps_post_needs_the_csrf_header(oauth, fake_google):
    client = APIClient(enforce_csrf_checks=True)

    assert client.post("/api/auth/oauth/finish", {"name": "A", "accept_terms": True}, format="json").status_code == 403

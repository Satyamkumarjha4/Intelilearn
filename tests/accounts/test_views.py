"""Unit under test: the auth views in `accounts.views` (register, verify, login, me, refresh, logout) with
`CookieJWTAuthentication` and CSRF.

Why: this is the whole sign-in flow. Tokens must stay in httpOnly cookies, cookie-authenticated writes must need the
CSRF header, and a refresh token must be rotated and the old one blacklisted, or a stolen token keeps working.

Use cases:
- register starts a pending sign-up: 202, a code mailed to the address as typed, the `lc_signup` ticket cookie, and no
  account, session or credits
- the right code makes the account (the email as typed, verified by code) and signs in with httpOnly cookies
- register for an address that has an account answers the same and mails its owner a notice instead
- register keeps when and to which version of the terms the person agreed, on the sign-up and then the account
- register refuses a person who has not confirmed the terms (a field error, nothing kept) and reports a weak password
  on the password field
- login accepts any email case and rejects a wrong password
- login refuses a deactivated account with the same answer as a wrong password, and sets no cookie
- /auth/me requires authentication and returns the signed-in user, with whether they are staff (the console's guard)
- a Bearer header works without CSRF; the auth endpoints and cookie-authenticated writes require it
- refresh rotates and blacklists the old token, and fails without a cookie or for a deactivated user
- logout clears the cookies and blacklists the refresh token, and succeeds without a session
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import PendingSignup, User

PASSWORD = "correct-horse-battery-staple"  # same as the `user` fixture in tests/conftest.py

pytestmark = pytest.mark.django_db


def cookie(client, name):
    morsel = client.cookies.get(name)
    return morsel.value if morsel else None


def is_cleared(response, name):
    return name in response.cookies and response.cookies[name]["max-age"] == 0


# --- register ---


def test_register_starts_a_signup_and_makes_no_account_session_or_credits(signup, mailbox):
    response = signup.register(email="Grace@Example.com")

    assert response.status_code == 202
    assert response.json() == {"status": "verification_required"}
    assert not User.objects.filter(email_canonical="grace@example.com").exists()  # no account until the code
    assert PendingSignup.objects.filter(email_canonical="grace@example.com").count() == 1
    assert not any(name in response.cookies for name in ("lc_access", "lc_refresh", "lc_session"))
    assert [m.kind for m in mailbox.to("Grace@example.com")] == ["signup_code"]  # mailed to the address as typed
    ticket = response.cookies["lc_signup"]
    assert ticket["httponly"] and ticket["path"] == "/api/auth" and ticket["samesite"] == "Lax"
    assert int(ticket["max-age"]) == 24 * 60 * 60  # the pending row's life


def test_the_right_code_makes_the_account_and_signs_in_with_httponly_cookies(signup):
    response = signup.complete(email="Grace@Example.com")

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "Grace@example.com"  # stored as typed: only the domain is lowercased
    assert response.json()["user"]["profile_complete"] is False
    assert User.objects.get(email_canonical="grace@example.com").is_email_verified

    access, refresh = response.cookies["lc_access"], response.cookies["lc_refresh"]
    assert access["httponly"] and refresh["httponly"]
    assert refresh["path"] == "/api/auth"
    assert response.cookies["lc_session"].value == "1"
    assert is_cleared(response, "lc_onboarded")
    assert is_cleared(response, "lc_signup")  # the ticket is spent


def test_register_for_an_existing_address_answers_the_same_and_tells_its_owner_instead(signup, mailbox, user):
    response = signup.register(email="ADA@example.com")

    assert response.status_code == 202 and response.json() == {"status": "verification_required"}
    assert not PendingSignup.objects.exists()
    assert [m.kind for m in mailbox.to(user.email)] == ["owner_notice"]  # to the address the account has


def test_register_rejects_weak_password_on_the_password_field(api_client):
    response = api_client.post(
        "/api/auth/register",
        {"email": "weak@example.com", "password": "12345", "name": "Weak", "accept_terms": True},
        format="json",
    )

    assert response.status_code == 400
    assert "password" in response.json()["fields"]
    assert not PendingSignup.objects.exists() and "lc_signup" not in response.cookies


def test_the_terms_the_person_agreed_to_are_kept_with_the_sign_up_and_then_the_account(signup):
    before = timezone.now()

    signup.register(email="grace@example.com")
    pending = PendingSignup.objects.get(email_canonical="grace@example.com")
    signup.verify("grace@example.com")

    grace = User.objects.get(email="grace@example.com")
    assert before <= pending.terms_accepted_at <= timezone.now()
    assert grace.terms_accepted_at == pending.terms_accepted_at
    assert grace.terms_version == User.TERMS_VERSION  # whatever the terms are today; bumped with them (docs/legal)


@pytest.mark.parametrize("consent", [{}, {"accept_terms": False}, {"accept_terms": None}])
def test_register_needs_the_terms_confirmed_and_keeps_nothing_without_it(api_client, consent):
    response = api_client.post(
        "/api/auth/register",
        {"email": "grace@example.com", "password": PASSWORD, "name": "Grace", **consent},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["fields"]["accept_terms"] == ["Please confirm to continue."]
    assert not PendingSignup.objects.exists() and not User.objects.filter(email="grace@example.com").exists()
    assert "lc_signup" not in response.cookies


def test_the_consent_is_not_part_of_what_the_api_says_about_a_person(signup):
    body = signup.complete().json()

    assert "accept_terms" not in body["user"] and "terms_version" not in body["user"]


def test_people_who_signed_up_before_the_terms_have_no_consent_on_record(user):
    assert user.terms_accepted_at is None and user.terms_version == ""


# --- login / me ---


def test_login_with_any_email_case(api_client, user):
    response = api_client.post("/api/auth/login", {"email": "ADA@EXAMPLE.COM", "password": PASSWORD}, format="json")

    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(user.id)
    assert cookie(api_client, "lc_access")


def test_login_wrong_password(api_client, user):
    response = api_client.post("/api/auth/login", {"email": user.email, "password": "nope"}, format="json")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password.", "code": "invalid_credentials"}
    assert "lc_access" not in response.cookies


def test_me_requires_authentication(api_client):
    response = api_client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_me_returns_the_signed_in_user(signed_in_client, user):
    response = signed_in_client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "profile_complete": False,
        "is_staff": False,
    }


def test_me_says_when_the_user_is_staff(api_client):
    staff = User.objects.create_user("staff@example.com", password=PASSWORD, name="Staff", is_staff=True, verified=True)
    api_client.post("/api/auth/login", {"email": staff.email, "password": PASSWORD}, format="json")

    assert api_client.get("/api/auth/me").json()["is_staff"] is True


def test_bearer_header_works_without_csrf(user):
    client = APIClient(enforce_csrf_checks=True)
    token = RefreshToken.for_user(user).access_token

    response = client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code == 200


# --- CSRF ---


def test_auth_endpoints_require_csrf_token(user):
    client = APIClient(enforce_csrf_checks=True)
    body = {"email": user.email, "password": PASSWORD}

    assert client.post("/api/auth/login", body, format="json").status_code == 403

    client.get("/api/auth/csrf")
    token = cookie(client, "csrftoken")
    assert client.post("/api/auth/login", body, format="json", HTTP_X_CSRFTOKEN=token).status_code == 200


def test_cookie_authenticated_writes_require_csrf_token(user):
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/auth/csrf")
    token = cookie(client, "csrftoken")
    client.post("/api/auth/login", {"email": user.email, "password": PASSWORD}, format="json", HTTP_X_CSRFTOKEN=token)

    without = client.patch("/api/profile", {"notes": "hi"}, format="json")
    with_token = client.patch("/api/profile", {"notes": "hi"}, format="json", HTTP_X_CSRFTOKEN=token)

    assert without.status_code == 403
    assert with_token.status_code == 200


# --- refresh / logout ---


def test_refresh_rotates_and_blacklists_the_old_token(signed_in_client):
    old_refresh = cookie(signed_in_client, "lc_refresh")

    response = signed_in_client.post("/api/auth/refresh")

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "ada@example.com"
    assert cookie(signed_in_client, "lc_refresh") != old_refresh

    replay = APIClient()
    replay.cookies["lc_refresh"] = old_refresh
    replayed = replay.post("/api/auth/refresh")
    assert replayed.status_code == 401
    assert replayed.json()["code"] == "session_expired"
    assert is_cleared(replayed, "lc_session")


def test_a_deactivated_account_cannot_sign_in_and_is_told_what_a_wrong_password_is_told(api_client, user):
    wrong = api_client.post("/api/auth/login", {"email": user.email, "password": "wrong"}, format="json")
    User.objects.filter(pk=user.pk).update(is_active=False)

    refused = api_client.post("/api/auth/login", {"email": user.email, "password": PASSWORD}, format="json")

    assert refused.status_code == 401
    assert refused.json() == wrong.json()  # nothing says the account exists, or that it was switched off
    assert not any(name in refused.cookies for name in ("lc_access", "lc_refresh", "lc_session"))


def test_refresh_without_cookie_is_unauthorised(api_client):
    assert api_client.post("/api/auth/refresh").status_code == 401


def test_refresh_fails_for_deactivated_user(signed_in_client, user):
    User.objects.filter(pk=user.pk).update(is_active=False)

    assert signed_in_client.post("/api/auth/refresh").status_code == 401


def test_logout_clears_cookies_and_blacklists_refresh(signed_in_client):
    refresh = cookie(signed_in_client, "lc_refresh")

    response = signed_in_client.post("/api/auth/logout")

    assert response.status_code == 204
    for name in ("lc_access", "lc_refresh", "lc_session", "lc_onboarded"):
        assert is_cleared(response, name)

    replay = APIClient()
    replay.cookies["lc_refresh"] = refresh
    assert replay.post("/api/auth/refresh").status_code == 401


def test_logout_without_session_still_succeeds(api_client):
    assert api_client.post("/api/auth/logout").status_code == 204

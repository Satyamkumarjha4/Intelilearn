import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User

PASSWORD = "correct-horse-battery-staple"  # same as the `user` fixture in tests/conftest.py

pytestmark = pytest.mark.django_db


def cookie(client, name):
    morsel = client.cookies.get(name)
    return morsel.value if morsel else None


def is_cleared(response, name):
    return name in response.cookies and response.cookies[name]["max-age"] == 0


# --- register ---


def test_register_signs_in_with_httponly_cookies(api_client):
    response = api_client.post(
        "/api/auth/register", {"email": "Grace@Example.com", "password": PASSWORD, "name": "Grace"}, format="json"
    )

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "grace@example.com"
    assert response.json()["user"]["profile_complete"] is False
    assert User.objects.filter(email="grace@example.com").exists()

    access, refresh = response.cookies["lc_access"], response.cookies["lc_refresh"]
    assert access["httponly"] and refresh["httponly"]
    assert refresh["path"] == "/api/auth"
    assert response.cookies["lc_session"].value == "1"
    assert is_cleared(response, "lc_onboarded")


def test_register_rejects_duplicate_email_case_insensitively(api_client, user):
    response = api_client.post(
        "/api/auth/register", {"email": "ADA@example.com", "password": PASSWORD, "name": "Ada"}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid"
    assert "email" in response.json()["fields"]


def test_register_rejects_weak_password_on_the_password_field(api_client):
    response = api_client.post(
        "/api/auth/register", {"email": "weak@example.com", "password": "12345", "name": "Weak"}, format="json"
    )

    assert response.status_code == 400
    assert "password" in response.json()["fields"]
    assert not User.objects.filter(email="weak@example.com").exists()


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
    assert response.json() == {"id": str(user.id), "email": user.email, "name": user.name, "profile_complete": False}


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

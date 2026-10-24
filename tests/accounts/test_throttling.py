import pytest
from rest_framework.throttling import SimpleRateThrottle

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"  # same as the `user` fixture in tests/conftest.py


@pytest.fixture
def rates(monkeypatch):
    """Throttle classes read the rates dict at import time, so patch the dict itself."""

    def _set(**values):
        for scope, rate in values.items():
            monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, rate)

    return _set


def login(client, email, password="wrong", ip="10.0.0.1"):
    return client.post("/api/auth/login", {"email": email, "password": password}, format="json", HTTP_X_FORWARDED_FOR=ip)


def test_login_is_limited_per_account_across_addresses(api_client, user, rates):
    rates(auth="100/min", auth_account="2/min")

    assert login(api_client, user.email, ip="10.0.0.1").status_code == 401
    assert login(api_client, user.email.upper(), ip="10.0.0.2").status_code == 401  # same account, any case
    blocked = login(api_client, user.email, password=PASSWORD, ip="10.0.0.3")

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "throttled"


def test_other_accounts_are_not_affected(api_client, user, rates):
    rates(auth="100/min", auth_account="1/min")
    login(api_client, "someone-else@example.com")

    assert login(api_client, user.email, password=PASSWORD).status_code == 200


def test_address_limit_uses_the_forwarded_client_address(api_client, rates):
    rates(auth="2/min", auth_account="100/min")
    login(api_client, "a@example.com", ip="10.0.0.1")
    login(api_client, "b@example.com", ip="10.0.0.1")

    assert login(api_client, "c@example.com", ip="10.0.0.1").status_code == 429
    # a different visitor behind the same proxy still gets through
    assert login(api_client, "c@example.com", ip="10.0.0.2").status_code == 401


def test_refresh_has_its_own_budget(signed_in_client, rates):
    rates(auth="1/min", auth_refresh="100/min")  # the login in the fixture used the only "auth" slot

    assert signed_in_client.post("/api/auth/refresh").status_code == 200

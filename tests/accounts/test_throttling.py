"""Unit under test: `accounts.throttling` (AuthRateThrottle per client address, LoginAccountThrottle per email) as
applied to the auth endpoints.

Why: without a per-account limit a password can be guessed from many addresses; without the forwarded client address
every visitor shares one bucket behind the Next.js proxy; and routine refreshes must not use up the login budget.

Use cases:
- registering is limited per client address, and another address is not affected
- login is limited per account, across client addresses
- the per-account limit counts by the canonical email, so an alias of the address shares the budget
- other accounts are not affected by one account's limit
- the per-address limit keys on the X-Forwarded-For client address
- token refresh has its own budget
"""

import pytest
from rest_framework.throttling import SimpleRateThrottle

from accounts.models import PendingSignup

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
    return client.post(
        "/api/auth/login", {"email": email, "password": password}, format="json", HTTP_X_FORWARDED_FOR=ip
    )


def register(client, n, ip="10.0.0.1"):
    return client.post(
        "/api/auth/register",
        {"email": f"new{n}@example.com", "password": PASSWORD, "name": "New", "accept_terms": True},
        format="json",
        HTTP_X_FORWARDED_FOR=ip,
    )


def test_registering_is_limited_per_client_address(api_client, rates):
    rates(auth="2/min", auth_account="100/min")
    assert register(api_client, 1).status_code == 202
    assert register(api_client, 2).status_code == 202

    blocked = register(api_client, 3)

    assert blocked.status_code == 429 and blocked.json()["code"] == "throttled"
    assert not PendingSignup.objects.filter(email="new3@example.com").exists()
    assert register(api_client, 4, ip="10.0.0.2").status_code == 202  # another visitor behind the same proxy


def test_login_is_limited_per_account_across_addresses(api_client, user, rates):
    rates(auth="100/min", auth_account="2/min")

    assert login(api_client, user.email, ip="10.0.0.1").status_code == 401
    assert login(api_client, user.email.upper(), ip="10.0.0.2").status_code == 401  # same account, any case
    blocked = login(api_client, user.email, password=PASSWORD, ip="10.0.0.3")

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "throttled"


def test_the_per_account_limit_counts_by_the_canonical_email_so_an_alias_cannot_dodge_it(api_client, user, rates):
    rates(auth="100/min", auth_account="2/min")

    assert login(api_client, "ada@example.com", ip="10.0.0.1").status_code == 401
    assert login(api_client, "Ada+one@example.com", ip="10.0.0.2").status_code == 401  # an alias: the same budget
    blocked = login(api_client, "ADA+two@example.com", password=PASSWORD, ip="10.0.0.3")

    assert blocked.status_code == 429


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

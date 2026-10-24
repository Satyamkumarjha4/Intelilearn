"""Fixtures shared by every backend test.

- `_clear_cache` (autouse): empties the cache around each test, because throttle counters and the resolved registry
  live there and would otherwise leak between tests.
- `api_client`: a DRF APIClient with no credentials.
- `user`: ada@example.com, with the shared test PASSWORD.
- `signed_in_client`: an APIClient signed in as `user` through the real login endpoint, so it carries the auth cookies.
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _clear_cache():
    # Throttle counters live in the cache; keep tests independent of each other.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    from accounts.models import User

    return User.objects.create_user("ada@example.com", password=PASSWORD, name="Ada Lovelace")


@pytest.fixture
def signed_in_client(api_client, user):
    response = api_client.post("/api/auth/login", {"email": user.email, "password": PASSWORD}, format="json")
    assert response.status_code == 200
    return api_client

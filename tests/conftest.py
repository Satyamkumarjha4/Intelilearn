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

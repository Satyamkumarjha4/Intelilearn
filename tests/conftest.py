"""Fixtures shared by every backend test.

- `_clear_cache` (autouse): empties the cache around each test, because throttle counters and the resolved registry
  live there and would otherwise leak between tests.
- `api_client`: a DRF APIClient with no credentials.
- `user`: ada@example.com, with the shared test PASSWORD.
- `signed_in_client`: an APIClient signed in as `user` through the real login endpoint, so it carries the auth cookies.
- `other_user`: a second learner (grace@example.com), to prove ownership checks.
- `credits_on` (`support/credits_fixtures.py`): the credit gate switched on, with the plan's prices and `fund(user, n)`;
  `_pin_the_open_gate` (autouse, same module) starts every test on `OpenGate` whatever the default becomes.
- `payments` (`support/payments.py`): a scripted payment gateway switched on, to buy, to send signed events and to read
  what happened.
- `_a_migration_test_leaves_the_schema_at_the_latest` (autouse, for `migration`-marked tests): fails a test that migrates
  the database back and does not bring it forward again. The next test on that worker (tests run in parallel, in any
  order) would otherwise meet an old schema.
- `make_lesson(**fields)`: creates lessons, by default owned by `user`; `lesson` is one at the first stage.
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

pytest_plugins = [
    "support.fixtures",
    "support.quiz_fixtures",
    "support.credits_fixtures",
    "support.payments",
]  # graph and flow fixtures, shared by tests/graph and tests/lessons

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _clear_cache():
    # Throttle counters live in the cache; keep tests independent of each other.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _a_migration_test_leaves_the_schema_at_the_latest(request):
    yield
    if request.node.get_closest_marker("migration") is None:
        return
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    behind = executor.migration_plan(executor.loader.graph.leaf_nodes())
    assert not behind, f"the test left these migrations unapplied for the next test: {[str(m) for m, _ in behind]}"


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


@pytest.fixture
def other_user(db):
    from accounts.models import User

    return User.objects.create_user("grace@example.com", password=PASSWORD, name="Grace Hopper")


@pytest.fixture
def make_lesson(user):
    from lessons.models import Lesson

    def _make(**fields):
        """A lesson. `final_test` is not a column any more: it stands for the questions the lesson was built with, which
        go on the record as its first set (`QuestionBank.set_first_set`)."""
        from support.first_sets import seed_first_set

        fields.setdefault("owner", user)
        fields.setdefault("topic", "Binary search")
        test = fields.pop("final_test", None)
        lesson = Lesson.objects.create(**fields)
        if test:
            seed_first_set(lesson, test["questions"])
        return lesson

    return _make


@pytest.fixture
def lesson(make_lesson):
    return make_lesson()

"""Fixtures shared by every backend test.

- `_clear_cache` (autouse): empties the cache around each test, because throttle counters and the resolved registry
  live there and would otherwise leak between tests.
- `_mail_goes_to_the_mailbox` (autouse): the mail backend is `recording` and queued mail is delivered at once, so no
  test needs a broker or sends anything; `mailbox` is where a test reads what was sent (`support/mail.py`).
- `fake_google` / `oauth`: the stand-in sign-in provider switched on, and `oauth.sign_in({...})` to drive the whole
  dance through the real endpoints (`support/oauth.py`); `support/oidc.py` is a Google that signs real ID tokens.
- `api_client`: a DRF APIClient with no credentials.
- `signup`: registers and verifies through the real endpoints (`support/signup.py`); `new_browser()` is another visitor
  with their own cookies (to play an attacker beside a victim).
- `user`: ada@example.com, with the shared test PASSWORD.
- `signed_in_client`: an APIClient signed in as `user` through the real login endpoint, so it carries the auth cookies.
- `other_user`: a second learner (grace@example.com), to prove ownership checks.
- `credits_on` (`support/credits_fixtures.py`): the credit gate switched on, with the plan's prices and `fund(user, n)`;
  `_pin_the_open_gate` (autouse, same module) starts every test on `OpenGate` whatever the default becomes.
- `payments` (`support/payments.py`): a scripted payment gateway switched on, to buy, to send signed events and to read
  what happened.
- `_a_migration_test_leaves_the_schema_at_the_latest` (autouse, for `migration`-marked tests): fails a test that
  migrates the database back and does not bring it forward again. The next test on that worker (tests run in parallel,
  in any order) would otherwise meet an old schema.
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


@pytest.fixture(autouse=True)
def _mail_goes_to_the_mailbox():
    """No test sends real mail or needs a broker: messages are delivered at once to the in-memory `MAILBOX`.

    It does not take the `settings` fixture: a test may use that name for a parameter of its own."""
    from django.test import override_settings
    from support.mail import MAILBOX

    MAILBOX.messages.clear()
    with override_settings(MAIL_BACKEND="recording", MAIL_DISPATCH="support.mail.InlineDispatch"):
        yield


@pytest.fixture
def mailbox():
    from support.mail import MAILBOX

    return MAILBOX


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def signup(api_client, django_capture_on_commit_callbacks):
    """Sign up through the real endpoints: `signup.complete(...)` registers and enters the mailed code."""
    from support.signup import Signup

    return Signup(api_client, django_capture_on_commit_callbacks)


@pytest.fixture
def fake_google(settings):
    """The stand-in sign-in provider switched on, as the throwaway stack has it, and a way to drive it."""
    settings.AUTH_PROVIDERS_ENABLED = ["fake"]
    settings.AUTH_ALLOW_FAKE_PROVIDER = True
    settings.AUTH_PUBLIC_BASE_URL = "http://localhost:3000"


@pytest.fixture
def oauth(api_client, django_capture_on_commit_callbacks, fake_google):
    """`oauth.sign_in({...})` signs in with the fake provider through the real endpoints (`support/oauth.py`)."""
    from support.oauth import OAuthFlow

    return OAuthFlow(api_client, django_capture_on_commit_callbacks)


@pytest.fixture
def new_browser(django_capture_on_commit_callbacks):
    """Another visitor, with their own cookies: `new_browser()` → a `Signup` on a fresh client."""
    from support.signup import Signup

    return lambda: Signup(APIClient(), django_capture_on_commit_callbacks)


@pytest.fixture
def user(db):
    from accounts.models import User

    return User.objects.create_user("ada@example.com", password=PASSWORD, name="Ada Lovelace", verified=True)


@pytest.fixture
def signed_in_client(api_client, user):
    response = api_client.post("/api/auth/login", {"email": user.email, "password": PASSWORD}, format="json")
    assert response.status_code == 200
    return api_client


@pytest.fixture
def other_user(db):
    from accounts.models import User

    return User.objects.create_user("grace@example.com", password=PASSWORD, name="Grace Hopper", verified=True)


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

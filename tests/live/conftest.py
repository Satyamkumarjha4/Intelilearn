"""Fixtures for the live suite: real models, real media services, the real sandbox. Run by hand: `pytest -m live`.

They spend money, using the keys in the environment (`.env`): each lesson is checked against `LIVE_MAX_COST_USD`
(default 2.00) from the `ModelCall` log, after it has run. The tests are skipped, with the reason, when the key is
missing. Nothing here runs under a plain `pytest` or `make check`.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _need_keys(request):
    """Live tests only: every other test in this folder (the offline checks) runs as usual."""
    if request.node.get_closest_marker("live") and not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is not set: the default registry's models need it (see docs/testing.md)")


@pytest.fixture
def real_registry(db):
    """The default registry (Gemini, with Groq Llama as fallback) loaded into the test database."""
    from lessons.checkpoints import CheckpointerFactory
    from llm_registry.seed import DefaultRegistry
    from llm_registry.serialization import RegistrySerializer

    RegistrySerializer().load(DefaultRegistry().build())
    CheckpointerFactory().setup()  # the checkpoint tables are not Django models, so the test database lacks them


@pytest.fixture
def learner(db):
    from accounts.models import User

    user = User.objects.create_user("golden@example.com", password="not-used-by-the-suite", name="Golden")
    profile = user.profile
    profile.education_level, profile.learning_preference, profile.goal = "undergraduate", "mixed", "deep_understanding"
    profile.save()
    return user


@pytest.fixture
def max_cost() -> float:
    return float(os.environ.get("LIVE_MAX_COST_USD", "2.00"))

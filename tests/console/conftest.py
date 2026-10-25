"""Fixtures for the console tests.

- `staff_user` / `staff_client`: a staff member, and an API client signed in as them through the real login endpoint.
- `learner_client`: a client signed in as the ordinary `user` of tests/conftest.py.
- `now`: the instant every time-dependent test runs at (2026-03-15 12:00 UTC, a Sunday), with `timezone.now` frozen to
  it, so ranges, daily series and `auto_now_add` stamps are the same on every run, at any hour.
- `make_call(**fields)`: a ModelCall row, by default a successful `learner.assess` call on gemini 30 minutes before
  `now`; `at=` (a datetime) or `ago=` (a timedelta) places it in time.
- `count_queries(fn)`: runs `fn()` and returns how many SQL queries it made; the tests compare a small data set with a
  larger one to prove an endpoint's query count does not grow with the data (no N+1).
- `registry`: gemini and groq providers (keys set in the environment), their models, and a `bind(node_key, model)`.

Test modules can't import from a conftest (importlib import mode), so the helpers are served as fixtures.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from llm_registry.models import LLMModel, ModelCall, NodeConfig, NodeModelBinding, Provider
from llm_registry.node_configs import NodeConfigSync

PASSWORD = "correct-horse-battery-staple"
NOW = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: NOW)
    return NOW


@pytest.fixture
def staff_user(db):
    return User.objects.create_user("root@example.com", password=PASSWORD, name="Root Admin", is_staff=True)


@pytest.fixture
def staff_client(staff_user):
    client = APIClient()
    assert (
        client.post("/api/auth/login", {"email": staff_user.email, "password": PASSWORD}, format="json").status_code
        == 200
    )
    return client


@pytest.fixture
def learner_client(signed_in_client):
    return signed_in_client


@pytest.fixture
def make_call(db, now):
    def _make(*, at=None, ago=timedelta(minutes=30), **fields):
        defaults = dict(node_key="learner.assess", provider_key="gemini", model_name="gemini-3.5-flash", attempt=1,
                        fallback_index=0, status=ModelCall.Status.OK, latency_ms=1000)  # fmt: skip
        call = ModelCall.objects.create(**{**defaults, **fields})
        ModelCall.objects.filter(pk=call.pk).update(created_at=at or now - ago)
        call.refresh_from_db()
        return call

    return _make


@pytest.fixture
def count_queries(db):
    def _count(fn):
        with CaptureQueriesContext(connection) as queries:
            fn()
        return len(queries)

    return _count


@pytest.fixture
def registry(db, monkeypatch):
    """Two providers with their keys set, one model each and one extra, and a way to bind them to nodes."""
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret-value-1")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret-value-2")
    NodeConfigSync().ensure()
    gemini = Provider.objects.create(key="gemini", kind="google_genai", api_key_env="GEMINI_API_KEY", rpm_limit=10)
    groq = Provider.objects.create(key="groq", kind="groq", api_key_env="GROQ_API_KEY")
    caps = dict(supports_structured_output=True, supports_tool_calling=True, supports_vision=True,
                context_window=1_000_000, max_output_tokens=65_536)  # fmt: skip
    models = {
        "flash": LLMModel.objects.create(
            provider=gemini, name="gemini-3.5-flash", default_params={"temperature": 0.5}, **caps
        ),  # fmt: skip
        "lite": LLMModel.objects.create(provider=gemini, name="gemini-3.5-flash-lite", **caps),
        "oss": LLMModel.objects.create(provider=groq, name="openai/gpt-oss-120b", **{**caps, "supports_vision": False}),
    }

    class Registry:
        providers = {"gemini": gemini, "groq": groq}

        def __init__(self):
            self.models = models

        def bind(self, node_key, model, priority=0, **fields):
            node = NodeConfig.objects.get(node_key=node_key)
            return NodeModelBinding.objects.create(node=node, model=models[model], priority=priority, **fields)

    return Registry()

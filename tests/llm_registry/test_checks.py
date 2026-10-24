"""Unit under test: `llm_registry.checks.RegistryHealth`, the `manage.py check` warnings (through the registered
`registry_check` hook) for registry problems that would otherwise surface only in the middle of a lesson.

Why: a required node with no usable model, or with models whose API keys are missing, fails the first lesson that
reaches it. The check says so at start-up, once per kind of problem rather than once per node.

Use cases:
- an empty registry warns that nodes have no usable model
- missing API keys are reported once, naming the variables to set
- a healthy registry has no warnings
"""

import pytest

from llm_registry.checks import registry_check
from llm_registry.seed import DefaultRegistry
from llm_registry.serialization import RegistrySerializer

pytestmark = pytest.mark.django_db


def ids(warnings):
    return {w.id for w in warnings}


def test_empty_registry_warns_about_missing_models(node_configs):
    assert ids(registry_check()) == {"llm_registry.W002"}


def test_missing_api_keys_are_reported_once(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    RegistrySerializer().load(DefaultRegistry().build())

    warnings = registry_check()

    assert ids(warnings) == {"llm_registry.W003"}
    assert "GEMINI_API_KEY" in warnings[0].hint


def test_healthy_registry_has_no_warnings(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    RegistrySerializer().load(DefaultRegistry().build())

    assert registry_check() == []

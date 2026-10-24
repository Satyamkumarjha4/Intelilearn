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

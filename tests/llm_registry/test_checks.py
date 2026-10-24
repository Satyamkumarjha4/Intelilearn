"""Unit under test: `llm_registry.checks.RegistryHealth`, the `manage.py check` warnings (through the registered
`registry_check` hook) for registry problems that would otherwise surface only in the middle of a lesson.

Why: a required node with no usable model, or with models whose API keys are missing, fails the first lesson that
reaches it. The check says so at start-up, once per kind of problem rather than once per node.

Use cases:
- an empty registry warns that nodes have no usable model
- missing API keys are reported once, naming the variables to set
- a healthy registry has no warnings
- tracing that is off warns of nothing; one that cannot work says what is missing, naming settings and never values
"""

import sys
from types import SimpleNamespace

import pytest

from llm_registry.checks import registry_check, tracing_check
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


class TestTracingCheck:
    def warnings(self, settings, name):
        settings.LLM_TRACING = name
        return tracing_check()

    def test_tracing_that_is_off_warns_of_nothing(self, settings):
        assert self.warnings(settings, "none") == [] and self.warnings(settings, "") == []

    def test_an_unknown_service_is_named_and_tracing_stays_off(self, settings):
        warnings = self.warnings(settings, "zipkin")

        assert ids(warnings) == {"llm_registry.W010"} and "zipkin" in warnings[0].msg

    def test_langsmith_without_its_key_names_the_variable(self, settings, monkeypatch):
        monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

        warnings = self.warnings(settings, "langsmith")

        assert ids(warnings) == {"llm_registry.W011"} and "LANGSMITH_API_KEY" in warnings[0].msg

    def test_langsmith_with_its_key_is_fine_and_the_value_is_never_reported(self, settings, monkeypatch):
        monkeypatch.setenv("LANGSMITH_API_KEY", "s3cret-value")

        assert self.warnings(settings, "langsmith") == []

    def test_langfuse_names_every_missing_key_and_not_their_values(self, settings, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-secret")
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        warnings = self.warnings(settings, "langfuse")

        assert "LANGFUSE_SECRET_KEY" in warnings[0].msg and "LANGFUSE_PUBLIC_KEY" not in warnings[0].msg
        assert "pk-secret" not in warnings[0].msg

    def test_langfuse_without_its_package_says_how_to_install_it(self, settings, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setitem(sys.modules, "langfuse", None)
        monkeypatch.setitem(sys.modules, "langfuse.langchain", None)

        warnings = self.warnings(settings, "langfuse")

        assert ids(warnings) == {"llm_registry.W012"} and "uv add langfuse" in warnings[0].msg

    def test_langfuse_with_keys_and_package_is_fine(self, settings, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        module = SimpleNamespace(CallbackHandler=object)
        monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(langchain=module))
        monkeypatch.setitem(sys.modules, "langfuse.langchain", module)

        assert self.warnings(settings, "langfuse") == []

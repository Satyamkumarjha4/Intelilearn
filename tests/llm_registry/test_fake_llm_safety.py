"""Unit under test: `llm_registry.checks.FakeLLMSafety`, the start-up refusals (through the registered
`fake_llm_is_not_in_production` hook) that keep the scripted fake LLM off a production host.

Why: the fake LLM answers every node with canned, schema-valid output and can be told to fail on cue. Behind a real
site it would hand every learner the same canned lesson and make the app look healthy while teaching nothing. Like the
fake payment gateway (`payments.E004`), it exists only on the throwaway stacks, which run with DEBUG on, and the
check makes that impossible to get wrong by refusing to start. The messages name the setting, never a value.

Use cases:
- with DEBUG on (the throwaway stacks) a registry that points at the fake and the fake's key are both fine
- with DEBUG off, an enabled provider that reads FAKE_LLM_API_KEY is refused (E001), naming the provider
- with DEBUG off, an enabled provider whose address is the fake server's is refused too (E001)
- a switched-off fake provider and real providers are not refused
- with DEBUG off, a FAKE_LLM_API_KEY that holds anything is refused (E002), and the message never holds the value;
  an empty one (the compose default) is fine
- a database that is not migrated yet has no providers to refuse, and is not an error
- the registered hook gives the same answer as the class
"""

import pytest
from django.db import DatabaseError

from llm_registry.checks import FakeLLMSafety, fake_llm_is_not_in_production
from llm_registry.models import Provider

pytestmark = pytest.mark.django_db


def ids(errors):
    return [e.id for e in errors]


@pytest.fixture
def production(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.delenv("FAKE_LLM_API_KEY", raising=False)  # a developer's own .env may hold one


class TestRegistryPointsAtTheFake:
    def test_with_debug_on_the_fake_provider_and_its_key_are_fine(self, settings, monkeypatch):
        settings.DEBUG = True
        monkeypatch.setenv("FAKE_LLM_API_KEY", "fake")
        Provider.objects.create(key="fake", kind="openai_compatible", api_key_env="FAKE_LLM_API_KEY")

        assert FakeLLMSafety().errors() == []

    def test_a_provider_that_reads_the_fake_key_is_refused_in_production_and_named(self, production):
        Provider.objects.create(key="scripted", kind="openai_compatible", api_key_env="FAKE_LLM_API_KEY")

        errors = FakeLLMSafety().errors()

        assert ids(errors) == ["llm_registry.E001"]
        assert "scripted" in errors[0].msg and "DJANGO_DEBUG" in errors[0].hint

    def test_a_provider_at_the_fake_servers_address_is_refused_in_production(self, production):
        Provider.objects.create(
            key="lan", kind="openai_compatible", api_key_env="OTHER_KEY", base_url="http://fake-llm.lan:9000/v1"
        )

        assert ids(FakeLLMSafety().errors()) == ["llm_registry.E001"]

    def test_a_switched_off_fake_provider_and_real_providers_are_not_refused(self, production):
        Provider.objects.create(key="fake", kind="openai_compatible", api_key_env="FAKE_LLM_API_KEY", is_enabled=False)
        Provider.objects.create(key="gemini", kind="google_genai", api_key_env="GEMINI_API_KEY")
        Provider.objects.create(
            key="proxy", kind="openai_compatible", api_key_env="PROXY_KEY", base_url="https://llm.example.com/v1"
        )

        assert FakeLLMSafety().errors() == []

    def test_a_database_that_is_not_migrated_yet_has_nothing_to_refuse(self, production):
        def not_migrated():
            raise DatabaseError("no such table")

        assert FakeLLMSafety(providers=not_migrated).errors() == []


class TestTheFakeKey:
    def test_a_key_that_holds_anything_is_refused_in_production_without_printing_it(self, production, monkeypatch):
        monkeypatch.setenv("FAKE_LLM_API_KEY", "s3cret-looking-value")

        errors = FakeLLMSafety().errors()

        assert ids(errors) == ["llm_registry.E002"]
        assert "s3cret-looking-value" not in errors[0].msg + errors[0].hint

    def test_an_empty_key_the_compose_default_is_fine(self, production, monkeypatch):
        monkeypatch.setenv("FAKE_LLM_API_KEY", "")

        assert FakeLLMSafety().errors() == []

    def test_with_debug_on_the_key_is_fine(self, settings, monkeypatch):
        settings.DEBUG = True
        monkeypatch.setenv("FAKE_LLM_API_KEY", "fake")

        assert FakeLLMSafety().errors() == []


def test_the_registered_hook_gives_the_same_answer_as_the_class(production, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_API_KEY", "fake")

    assert ids(fake_llm_is_not_in_production()) == ids(FakeLLMSafety().errors()) == ["llm_registry.E002"]

"""Unit under test: what `RegistryResolver` does with the new per-layer settings: a layer whose provider has no key,
the output cap, timeout and structured mode of a binding, the model's reasoning levels and "off" mode, and the request
size limit of a model.

Why: the strategy (docs/to_be_developed/model-strategy.md 3.2, 3.5.B, 5.1) puts several layers behind each node, some
of which need keys that do not exist yet (OpenAI, Anthropic) or a request small enough for a per-minute token limit
(Groq at 8K). A layer that can only fail must not be tried on every call, a layer that can only exceed the limit must
not be offered, and every setting a layer has must reach the gateway.

Use cases:
- a layer whose provider's key is not set is skipped when the chain is resolved, and kept once the key is set
- a provider that needs no key (local) is never skipped
- a binding's output cap becomes `max_tokens` (and wins over the model's and the node's)
- a binding's timeout, structured mode and fall-through events reach the resolved layer
- structured mode is strict when the model can guarantee the schema, best effort otherwise, and a binding can say so
- effort none on a model with an "off" mode resolves to that mode's parameters, not to nothing
- a model with a request limit refuses a binding whose prompt plus reply could pass it, and takes one that fits
- a snapshot stored before these settings existed still loads
"""

import pytest

from llm_registry.models import LLMModel
from llm_registry.resolver import RegistryResolver, ResolvedModel

pytestmark = pytest.mark.django_db


def chain(key="learner.assess"):
    return RegistryResolver().resolve()[key].chain


class TestMissingKeys:
    def test_a_layer_whose_provider_has_no_key_is_skipped_until_the_key_is_set(
        self, node_configs, flash, llama, bind, monkeypatch
    ):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GROQ_API_KEY", "k")
        bind("learner.assess", flash, priority=0)
        bind("learner.assess", llama, priority=1)

        assert [m.model_name for m in chain()] == ["llama"]

        monkeypatch.setenv("GEMINI_API_KEY", "k")
        RegistryResolver().invalidate()

        assert [m.model_name for m in chain()] == ["gemini-flash", "llama"]

    def test_a_provider_that_needs_no_key_is_never_skipped(self, node_configs, llama, bind, groq):
        groq.api_key_env = ""
        groq.save()
        bind("learner.assess", llama)

        assert [m.model_name for m in chain()] == ["llama"]


class TestBindingSettings:
    def test_the_output_cap_becomes_max_tokens_and_wins(self, node_configs, llama, bind):
        node_configs["learner.assess"].params_override = {"max_tokens": 4000}
        node_configs["learner.assess"].save()
        bind("learner.assess", llama, max_output_tokens=900)

        assert chain()[0].params["max_tokens"] == 900

    def test_timeout_structured_mode_and_fall_through_events_reach_the_layer(self, node_configs, llama, bind):
        bind("learner.assess", llama, timeout_s=7, structured_mode="off", fall_through_on=["quota", "validation"])

        layer = chain()[0]

        assert (layer.timeout_s, layer.structured_mode, layer.fall_through_on) == (7, "off", ["quota", "validation"])

    def test_structured_mode_is_strict_when_the_model_can_guarantee_it_and_best_effort_otherwise(
        self, node_configs, llama, flash, bind
    ):
        llama.strict_structured = True
        llama.save()
        bind("learner.assess", llama, priority=0)
        bind("learner.assess", flash, priority=1)

        assert [m.structured_mode for m in chain()] == ["strict", "best_effort"]

    def test_a_binding_can_ask_for_best_effort_on_a_strict_model(self, node_configs, llama, bind):
        llama.strict_structured = True
        llama.save()
        bind("learner.assess", llama, structured_mode="best_effort")

        assert chain()[0].structured_mode == "best_effort"


class TestReasoning:
    def test_effort_none_resolves_to_the_models_off_mode(self, node_configs, groq, bind):
        model = LLMModel.objects.create(
            provider=groq, name="oss", supports_structured_output=True, supports_reasoning=True,
            reasoning_control="effort", reasoning_levels=["low", "medium", "high"], reasoning_off="unsupported",
            max_output_tokens=32_768, context_window=131_072,
        )  # fmt: skip
        node_configs["learner.assess"].reasoning_effort = "none"
        node_configs["learner.assess"].save()
        bind("learner.assess", model)

        layer = chain()[0]

        assert layer.reasoning == {"reasoning_effort": "low"}

    def test_a_model_with_no_off_mode_keeps_the_old_behaviour(self, node_configs, flash, bind):
        node_configs["learner.assess"].reasoning_effort = "none"
        node_configs["learner.assess"].save()
        bind("learner.assess", flash)

        assert chain()[0].reasoning == {}


class TestRequestLimit:
    @pytest.fixture
    def small(self, groq):
        return LLMModel.objects.create(
            provider=groq, name="oss", supports_structured_output=True, max_output_tokens=65_536,
            context_window=131_072, max_request_tokens=6000,
        )  # fmt: skip

    def test_a_binding_that_could_pass_the_limit_is_refused(self, node_configs, small, bind):
        bind("diagnostic.generate", small, max_output_tokens=8000)  # the node's prompt is about 1.5K

        assert chain("diagnostic.generate") == []

    def test_a_binding_with_no_output_cap_counts_as_the_models_full_output(self, node_configs, small, bind):
        bind("learner.assess", small)

        assert chain() == []

    def test_a_binding_that_fits_is_taken(self, node_configs, small, bind):
        bind("diagnostic.generate", small, max_output_tokens=4400)

        assert len(chain("diagnostic.generate")) == 1

    def test_a_model_with_no_limit_takes_any_cap(self, node_configs, llama, bind):
        bind("diagnostic.generate", llama, max_output_tokens=20_000)

        assert len(chain("diagnostic.generate")) == 1


def test_a_snapshot_stored_before_these_settings_existed_still_loads():
    old = dict(provider_key="g", provider_kind="google_genai", model_name="m", params={}, reasoning={},
               reasoning_effort="none", structured_output_method="json_schema", api_key_env="", base_url="",
               max_retries=2)  # fmt: skip

    model = ResolvedModel(**old)

    assert (model.timeout_s, model.structured_mode, model.fall_through_on) == (None, "best_effort", [])

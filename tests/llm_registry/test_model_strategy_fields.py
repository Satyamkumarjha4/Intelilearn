"""Unit under test: the validation of the strategy settings on `LLMModel` and `NodeModelBinding`
(docs/to_be_developed/model-strategy.md 3.5.B): reasoning levels, Claude 5 and thinking budgets, fall-through events and
the request size limit.

Why: these settings are typed by an admin or loaded from a seed, and a wrong one is a 400 from a provider or a silently
ignored setting mid-lesson. They must be refused when saved.

Use cases:
- a model's reasoning levels are a list of level names
- a Claude 5 model cannot be given a thinking-token budget control, an older one can, and effort control is always fine
- a binding's fall-through events are a list of known events
- a binding whose prompt plus reply could exceed the model's request limit is refused with the numbers in the message
- a new `ModelCall` has no cached, cache-write or dollar figures until a reply reports them
"""

import pytest
from django.core.exceptions import ValidationError

from llm_registry.models import LLMModel, ModelCall, NodeModelBinding, Provider

pytestmark = pytest.mark.django_db


def anthropic_model(name, control):
    provider, _ = Provider.objects.get_or_create(key="anthropic", kind="anthropic", api_key_env="ANTHROPIC_API_KEY")
    return LLMModel(provider=provider, name=name, supports_reasoning=True, reasoning_control=control)


def test_reasoning_levels_must_be_a_list_of_names(gemini):
    model = LLMModel(provider=gemini, name="m", reasoning_levels={"low": True})

    with pytest.raises(ValidationError) as caught:
        model.full_clean()

    assert "reasoning_levels" in caught.value.message_dict


@pytest.mark.parametrize("name", ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-2"])
def test_a_claude_5_model_cannot_use_a_thinking_budget(name):
    with pytest.raises(ValidationError) as caught:
        anthropic_model(name, "budget_tokens").full_clean()

    assert "budget_tokens" in caught.value.message_dict["reasoning_control"][0]


def test_an_older_claude_model_may_use_a_budget_and_effort_is_always_fine():
    anthropic_model("claude-haiku-4-5-20251001", "budget_tokens").full_clean()
    anthropic_model("claude-haiku-5-5", "effort").full_clean()


def test_a_binding_needs_known_fall_through_events(node_configs, flash):
    binding = NodeModelBinding(node=node_configs["learner.assess"], model=flash, fall_through_on=["quota", "weather"])

    with pytest.raises(ValidationError) as caught:
        binding.full_clean()

    assert "weather" in " ".join(caught.value.messages) or "fall_through_on" in " ".join(caught.value.messages)


def test_a_binding_over_the_models_request_limit_is_refused_with_the_numbers(node_configs, groq):
    model = LLMModel.objects.create(
        provider=groq, name="oss", supports_structured_output=True, max_output_tokens=65_536,
        context_window=131_072, max_request_tokens=6000,
    )  # fmt: skip
    binding = NodeModelBinding(node=node_configs["diagnostic.generate"], model=model, max_output_tokens=8000)

    with pytest.raises(ValidationError) as caught:
        binding.full_clean()

    message = " ".join(caught.value.messages)
    assert "6000" in message and "1500" in message and "8000" in message


def test_a_new_model_call_has_no_cache_or_dollar_figures():
    call = ModelCall.objects.create(node_key="x", provider_key="p", model_name="m", attempt=1, fallback_index=0,
                                    status="ok", latency_ms=1)  # fmt: skip

    assert (call.cached_input_tokens, call.cache_write_tokens, call.cost_usd) == (None, None, None)

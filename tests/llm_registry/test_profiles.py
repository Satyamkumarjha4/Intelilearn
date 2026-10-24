"""Unit under test: `llm_registry.profiles`, one ProviderProfile per provider kind (allowed params, renames,
reasoning translation) behind the ProviderProfiles registry.

Why: these rules decide what reaches each vendor's API. A wrong parameter name is silently ignored or rejected
by the provider, so a node would run without the reasoning or limits the admin configured, or fail mid-lesson.

Use cases:
- accepts parameters the provider kind supports
- rejects a parameter the provider kind doesn't support
- reports type errors for numbers, counts and stop lists
- requires params to be a JSON object
- renames max_tokens to num_predict for Ollama
- translates each reasoning effort and control into the provider's own parameter
- drops sampling params while reasoning is on when the model requires it
- keeps sampling params when reasoning is off
- raises max_tokens so a thinking budget leaves room for the answer
- refuses an unknown provider kind
"""

import pytest

from llm_registry.profiles import PROVIDER_PROFILES, UnknownProviderKind


def profile(kind):
    return PROVIDER_PROFILES.for_kind(kind)


def test_valid_params_pass():
    params = {"temperature": 0.4, "top_k": 40, "max_tokens": 1000, "stop": ["END"]}
    assert profile("google_genai").validate_params(params) == []


def test_unknown_param_for_provider_is_rejected():
    problems = profile("groq").validate_params({"top_p": 0.9})
    assert problems and "not supported" in problems[0]


def test_type_errors_are_reported():
    problems = profile("openai").validate_params({"temperature": "hot", "max_tokens": -1, "stop": "END"})
    assert len(problems) == 3


def test_params_must_be_an_object():
    assert profile("openai").validate_params([1, 2])


def test_ollama_renames_max_tokens():
    assert profile("ollama").to_integration_kwargs({"max_tokens": 500, "temperature": 0.1}) == {
        "num_predict": 500,
        "temperature": 0.1,
    }


@pytest.mark.parametrize(
    ("kind", "control", "effort", "expected"),
    [
        ("openai", "effort", "high", {"reasoning_effort": "high"}),
        ("groq", "effort", "low", {"reasoning_effort": "low"}),
        ("openai_compatible", "effort", "medium", {"reasoning_effort": "medium"}),
        ("anthropic", "effort", "high", {"effort": "high"}),
        ("anthropic", "budget_tokens", "low", {"thinking": {"type": "enabled", "budget_tokens": 2048}}),
        ("google_genai", "budget_tokens", "medium", {"thinking_budget": 8192}),
        ("google_genai", "effort", "high", {"thinking_level": "high"}),
        ("ollama", "effort", "low", {"reasoning": True}),
        ("ollama", "effort", "none", {"reasoning": False}),
        ("openai", "effort", "none", {}),
        ("openai", "none", "high", {}),
    ],
)
def test_translation_per_provider(kind, control, effort, expected):
    assert profile(kind).reasoning_kwargs(control, effort) == expected


def test_sampling_params_dropped_when_required():
    params, extra = profile("anthropic").apply_reasoning(
        "effort", "high", {"temperature": 0.3, "top_p": 0.9, "max_tokens": 100}, disables_sampling=True
    )
    assert params == {"max_tokens": 100}
    assert extra == {"effort": "high"}


def test_sampling_params_kept_when_reasoning_off():
    params, _ = profile("anthropic").apply_reasoning("effort", "none", {"temperature": 0.3}, disables_sampling=True)
    assert params == {"temperature": 0.3}


def test_thinking_budget_leaves_room_for_the_answer():
    params, extra = profile("anthropic").apply_reasoning(
        "budget_tokens", "high", {"max_tokens": 1000}, disables_sampling=False
    )
    assert params["max_tokens"] > extra["thinking"]["budget_tokens"]


def test_unknown_provider_kind_is_refused():
    with pytest.raises(UnknownProviderKind):
        profile("not-a-kind")

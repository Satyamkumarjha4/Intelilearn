import pytest

from llm_registry.reasoning import apply_reasoning, reasoning_kwargs


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
    assert reasoning_kwargs(kind, control, effort) == expected


def test_sampling_params_dropped_when_required():
    params, extra = apply_reasoning(
        "anthropic", "effort", "high", {"temperature": 0.3, "top_p": 0.9, "max_tokens": 100}, disables_sampling=True
    )
    assert params == {"max_tokens": 100}
    assert extra == {"effort": "high"}


def test_sampling_params_kept_when_reasoning_off():
    params, _ = apply_reasoning("anthropic", "effort", "none", {"temperature": 0.3}, disables_sampling=True)
    assert params == {"temperature": 0.3}


def test_thinking_budget_leaves_room_for_the_answer():
    params, extra = apply_reasoning("anthropic", "budget_tokens", "high", {"max_tokens": 1000}, disables_sampling=False)
    assert params["max_tokens"] > extra["thinking"]["budget_tokens"]

"""Unit under test: how each provider profile turns the generic settings (effort, "no reasoning", sampling, client
options) into that provider's own parameters: the table in docs/to_be_developed/model-strategy.md 3.5.A.

Why: a wrong parameter is a hard 400 the first day a key is added, or a silent default: "effort none" sent as nothing
means the provider's own default thinking (Gemini 3.6 Flash thinks at medium, Hydrogen at high, Claude Sonnet 5.5 at
high), which is the most expensive setting, not off. Each provider has a different way to ask for "none", and some
models cannot be turned off at all.

Use cases:
- for every provider and model kind, each effort (none, low, medium, high) gives the exact parameters of the table
- a model that cannot be turned off gets its lowest level for "none"; Gemini 3.8 Flash and Gemini 4 never get
  `minimal` (it returns an error); a model that can be switched off gets the switch (Claude Haiku 5.5's disabled
  thinking, OpenAI's effort none)
- a model with no `reasoning_off` setting keeps the old behaviour: "none" sends nothing
- an effort the model does not accept is lowered to the nearest level it does (never raised)
- Anthropic never sends temperature, top_p or top_k (they are a 400 from API version 2026-10-21): they are refused in
  settings and dropped from the client's parameters
- Claude 5.x models refuse a thinking-token budget (budget_tokens is a 400); older ones still take it
- OpenAI models use the Responses API (structured output and tools need it); OpenAI-compatible servers do not
- applying reasoning does not drop sampling parameters when the effort is none, and does when thinking is on and the
  model asks for it
"""

import pytest

from llm_registry.profiles import PROVIDER_PROFILES, ProviderKind

LOW_UP = ["low", "medium", "high"]
FROM_MINIMAL = ["minimal", "low", "medium", "high"]


def kwargs(kind, effort, *, control="effort", levels=(), off=""):
    return PROVIDER_PROFILES.for_kind(kind).reasoning_kwargs(control, effort, levels=levels, off=off)


# kind, levels, off, expected for effort none / low / medium / high
GRID = [
    ("gemini lite", ProviderKind.GOOGLE_GENAI, FROM_MINIMAL, "minimal",
     [{"thinking_level": "minimal"}, {"thinking_level": "low"}, {"thinking_level": "medium"},
      {"thinking_level": "high"}]),
    ("gemini 3.8 flash", ProviderKind.GOOGLE_GENAI, LOW_UP, "unsupported",
     [{"thinking_level": "low"}, {"thinking_level": "low"}, {"thinking_level": "medium"}, {"thinking_level": "high"}]),
    ("gemini 4 hydrogen", ProviderKind.GOOGLE_GENAI, [*LOW_UP, "xhigh"], "unsupported",
     [{"thinking_level": "low"}, {"thinking_level": "low"}, {"thinking_level": "medium"}, {"thinking_level": "high"}]),
    ("groq gpt-oss", ProviderKind.GROQ, LOW_UP, "unsupported",
     [{"reasoning_effort": "low"}, {"reasoning_effort": "low"}, {"reasoning_effort": "medium"},
      {"reasoning_effort": "high"}]),
    ("openai luna", ProviderKind.OPENAI, LOW_UP, "none",
     [{"reasoning_effort": "none"}, {"reasoning_effort": "low"}, {"reasoning_effort": "medium"},
      {"reasoning_effort": "high"}]),
    ("openai astra", ProviderKind.OPENAI, LOW_UP, "unsupported",
     [{"reasoning_effort": "low"}, {"reasoning_effort": "low"}, {"reasoning_effort": "medium"},
      {"reasoning_effort": "high"}]),
    ("anthropic haiku 5.5", ProviderKind.ANTHROPIC, LOW_UP, "disabled",
     [{"thinking": {"type": "disabled"}}, {"effort": "low"}, {"effort": "medium"}, {"effort": "high"}]),
    ("anthropic sonnet 5.5", ProviderKind.ANTHROPIC, LOW_UP, "unsupported",
     [{"effort": "low"}, {"effort": "low"}, {"effort": "medium"}, {"effort": "high"}]),
]  # fmt: skip


@pytest.mark.parametrize(("name", "kind", "levels", "off", "expected"), GRID, ids=[g[0] for g in GRID])
def test_each_effort_gives_the_providers_own_parameters(name, kind, levels, off, expected):
    got = [kwargs(kind, effort, levels=levels, off=off) for effort in ("none", "low", "medium", "high")]

    assert got == expected


@pytest.mark.parametrize("kind", [ProviderKind.GOOGLE_GENAI, ProviderKind.GROQ, ProviderKind.OPENAI,
                                  ProviderKind.ANTHROPIC])  # fmt: skip
def test_a_model_without_a_reasoning_off_setting_keeps_the_old_behaviour(kind):
    assert kwargs(kind, "none") == {}


def test_an_effort_the_model_does_not_accept_is_lowered_never_raised():
    assert kwargs(ProviderKind.GROQ, "medium", levels=["low", "high"]) == {"reasoning_effort": "low"}
    assert kwargs(ProviderKind.GROQ, "high", levels=["low", "medium"]) == {"reasoning_effort": "medium"}
    assert kwargs(ProviderKind.GROQ, "low", levels=["medium", "high"]) == {"reasoning_effort": "medium"}


def test_a_thinking_budget_model_with_no_off_switch_gets_the_smallest_budget():
    budgets = {"low": 1024, "medium": 8192, "high": 24576}
    profile = type(PROVIDER_PROFILES.for_kind(ProviderKind.GOOGLE_GENAI))(budgets)

    assert profile.reasoning_kwargs("budget_tokens", "none", off="unsupported") == {"thinking_budget": 1024}
    assert profile.reasoning_kwargs("budget_tokens", "none", off="minimal") == {"thinking_budget": 0}


class TestAnthropic:
    profile = PROVIDER_PROFILES.for_kind(ProviderKind.ANTHROPIC)

    @pytest.mark.parametrize("param", ["temperature", "top_p", "top_k"])
    def test_sampling_parameters_are_refused_in_settings(self, param):
        problems = self.profile.validate_params({param: 0.5})

        assert problems and param in problems[0]

    def test_sampling_parameters_are_dropped_from_the_clients_parameters(self):
        sent = self.profile.to_integration_kwargs({"temperature": 0.2, "top_p": 1, "top_k": 3, "max_tokens": 100})

        assert sent == {"max_tokens": 100}

    @pytest.mark.parametrize("name", ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-2"])
    def test_a_claude_5_model_refuses_a_thinking_budget(self, name):
        assert "budget_tokens" in self.profile.rejects_reasoning_control(name, "budget_tokens")
        assert self.profile.rejects_reasoning_control(name, "effort") == ""

    def test_an_older_claude_model_still_takes_a_budget(self):
        assert self.profile.rejects_reasoning_control("claude-haiku-4-5-20251001", "budget_tokens") == ""


def test_openai_uses_the_responses_api_and_openai_compatible_servers_do_not():
    assert PROVIDER_PROFILES.for_kind(ProviderKind.OPENAI).client_kwargs == {"use_responses_api": True}
    assert PROVIDER_PROFILES.for_kind(ProviderKind.OPENAI_COMPATIBLE).client_kwargs == {}
    assert PROVIDER_PROFILES.for_kind(ProviderKind.GROQ).client_kwargs == {}


class TestApplyReasoning:
    profile = PROVIDER_PROFILES.for_kind(ProviderKind.OPENAI)

    def test_sampling_stays_when_reasoning_is_off(self):
        params, extra = self.profile.apply_reasoning(
            "effort", "none", {"temperature": 0.4}, disables_sampling=True, levels=LOW_UP, off="none"
        )

        assert params == {"temperature": 0.4} and extra == {"reasoning_effort": "none"}

    def test_sampling_goes_when_thinking_is_on_and_the_model_asks_for_it(self):
        params, extra = self.profile.apply_reasoning(
            "effort", "low", {"temperature": 0.4, "max_tokens": 9}, disables_sampling=True, levels=LOW_UP, off="none"
        )

        assert params == {"max_tokens": 9} and extra == {"reasoning_effort": "low"}

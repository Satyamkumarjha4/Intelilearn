"""What differs between LLM vendors, one ProviderProfile per provider kind (Strategy).

Admins write provider-neutral parameter names (temperature, max_tokens, ...) and one reasoning effort
(none/low/medium/high). Each profile says which names its LangChain integration accepts, how a few are spelled
(Ollama's max_tokens -> num_predict) and how the effort becomes the integration's own parameter. Names were
checked against the installed langchain-* packages (tests/llm_registry/test_providers.py builds each client):

  OpenAI / OpenAI-compatible / Groq   reasoning_effort="low|medium|high"
  Anthropic                           effort="low|medium|high"            (reasoning_control=effort)
                                      thinking={"type": "enabled", ...}    (reasoning_control=budget_tokens)
  Google Gemini                       thinking_level="low|medium|high"     (reasoning_control=effort)
                                      thinking_budget=<tokens>             (reasoning_control=budget_tokens)
  Ollama                              reasoning=True/False

A new provider kind is a new ProviderProfile subclass registered in ProviderProfiles, plus a ProviderKind value.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from django.conf import settings


class ProviderKind:
    GOOGLE_GENAI = "google_genai"
    GROQ = "groq"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"

    CHOICES = [
        (GOOGLE_GENAI, "Google Gemini (langchain-google-genai)"),
        (GROQ, "Groq (langchain-groq)"),
        (OPENAI, "OpenAI (langchain-openai)"),
        (ANTHROPIC, "Anthropic (langchain-anthropic)"),
        (OLLAMA, "Ollama (langchain-ollama)"),
        (OPENAI_COMPATIBLE, "OpenAI-compatible API, e.g. OpenRouter or vLLM (langchain-openai)"),
    ]


class ReasoningOff:
    """How a model is told to think as little as it can (effort "none")."""

    UNSUPPORTED = "unsupported"  # it cannot be switched off: its lowest level
    MINIMAL = "minimal"  # a minimal level (Gemini lite models), or a budget of 0
    DISABLED = "disabled"  # a switch (Claude Haiku 5.5: thinking disabled)
    NONE = "none"  # effort none (OpenAI Luna and Terra)

    CHOICES = [
        (UNSUPPORTED, "Cannot be turned off (use the lowest level)"),
        (MINIMAL, "A minimal level"),
        (DISABLED, "A disabled switch"),
        (NONE, "Effort none"),
    ]


class ReasoningControl:
    EFFORT = "effort"
    BUDGET_TOKENS = "budget_tokens"
    NONE = "none"

    CHOICES = [
        (EFFORT, "Effort level (low / medium / high)"),
        (BUDGET_TOKENS, "Thinking-token budget"),
        (NONE, "No reasoning control"),
    ]


SAMPLING_PARAMS = frozenset({"temperature", "top_p", "top_k"})
#: reasoning levels, lowest first (a model lists the ones it accepts; an effort it does not accept is lowered)
LEVEL_LADDER = ("minimal", "low", "medium", "high", "xhigh", "max")
_NUMBER_PARAMS = frozenset({"temperature", "top_p", "presence_penalty", "frequency_penalty"})
_COUNT_PARAMS = frozenset({"max_tokens", "top_k", "seed"})
# Room left for the answer when a thinking budget counts against max_tokens.
_ANSWER_HEADROOM_TOKENS = 4096


class UnknownProviderKind(ValueError):
    pass


class ProviderProfile(ABC):
    kind: ClassVar[str]
    langchain_provider: ClassVar[str]  # init_chat_model(model_provider=...)
    allowed_params: ClassVar[frozenset[str]]
    renames: ClassVar[Mapping[str, str]] = {}
    needs_base_url: ClassVar[bool] = False
    needs_api_key: ClassVar[bool] = True
    supports_client_timeout: ClassVar[bool] = True  # the client takes timeout= and max_retries=

    def __init__(self, budgets: Mapping[str, int] | None = None):
        self._budgets = budgets

    def rejects_reasoning_control(self, model_name: str, control: str) -> str:
        """Why this reasoning control cannot be used with this model id (empty when it can)."""
        return ""

    @property
    def budgets(self) -> Mapping[str, int]:
        # Read lazily so the default registry, built at import, follows settings overridden in tests.
        return self._budgets if self._budgets is not None else settings.LLM_REASONING_BUDGETS

    def validate_params(self, params: Any) -> list[str]:
        """Human-readable problems with a params dict for this provider kind (empty if fine)."""
        if not isinstance(params, dict):
            return ['Parameters must be a JSON object, e.g. {"temperature": 0.4}.']
        problems = []
        for key, value in params.items():
            if key not in self.allowed_params:
                allowed = ", ".join(sorted(self.allowed_params))
                problems.append(f"'{key}' is not supported for this provider; allowed: {allowed}.")
            elif key in _NUMBER_PARAMS and not isinstance(value, int | float):
                problems.append(f"'{key}' must be a number.")
            elif key in _COUNT_PARAMS and (not isinstance(value, int) or value < 0):
                problems.append(f"'{key}' must be a non-negative integer.")
            elif key == "stop" and not (isinstance(value, list) and all(isinstance(s, str) for s in value)):
                problems.append("'stop' must be a list of strings.")
        return problems

    def to_integration_kwargs(self, params: dict) -> dict:
        return {self.renames.get(key, key): value for key, value in params.items()}

    #: extra options every client of this provider is built with
    client_kwargs: ClassVar[Mapping[str, Any]] = {}
    #: whether `with_structured_output(..., strict=True)` asks this provider to guarantee the schema
    supports_strict: ClassVar[bool] = False

    def reasoning_kwargs(self, control: str, effort: str, *, levels: Sequence[str] = (), off: str = "") -> dict:
        """Extra chat-model kwargs for this effort; {} when reasoning is not controllable.

        `levels` are the levels the model accepts (empty: low, medium, high); an effort it does not accept is lowered to
        the nearest it does. Effort "none" is how the model is told to think as little as it can: `off` says how (see
        `ReasoningOff`); with no `off` nothing is sent and the provider's own default thinking applies."""
        if control == ReasoningControl.NONE:
            return {}
        if effort == "none":
            return self._off_kwargs(control, off, self._ladder(levels))
        return self._reasoning_kwargs(control, self._accepted(effort, self._ladder(levels)))

    @staticmethod
    def _ladder(levels: Sequence[str]) -> list[str]:
        return [level for level in LEVEL_LADDER if level in levels]

    @staticmethod
    def _accepted(effort: str, ladder: list[str]) -> str:
        """The level the model accepts that is nearest the one asked for, never above it unless every level is."""
        if not ladder or effort in ladder:
            return effort
        rank = LEVEL_LADDER.index
        below = [level for level in ladder if rank(level) <= rank(effort)]
        return below[-1] if below else ladder[0]

    def _off_kwargs(self, control: str, off: str, ladder: list[str]) -> dict:
        """What "no reasoning" is for this provider: nothing unless the model says how it is asked for."""
        return {}

    @abstractmethod
    def _reasoning_kwargs(self, control: str, effort: str) -> dict:
        """The integration's parameter for an active effort (low/medium/high) under this control."""

    def apply_reasoning(
        self,
        control: str,
        effort: str,
        params: dict,
        *,
        disables_sampling: bool,
        levels: Sequence[str] = (),
        off: str = "",
    ) -> tuple[dict, dict]:
        """Return (params, reasoning_kwargs) with sampling params removed and max_tokens raised where needed."""
        extra = self.reasoning_kwargs(control, effort, levels=levels, off=off)
        active = effort != "none" and bool(extra) and extra.get("reasoning", True) is not False
        params = dict(params)
        if active and disables_sampling:
            for key in SAMPLING_PARAMS:
                params.pop(key, None)
        if "thinking" in extra and "budget_tokens" in extra["thinking"]:
            budget = extra["thinking"]["budget_tokens"]
            params["max_tokens"] = max(params.get("max_tokens", 0), budget + _ANSWER_HEADROOM_TOKENS)
        return params, extra


class OpenAIProfile(ProviderProfile):
    kind = ProviderKind.OPENAI
    langchain_provider = "openai"
    allowed_params = frozenset(
        {"temperature", "top_p", "max_tokens", "stop", "seed", "presence_penalty", "frequency_penalty"}
    )

    #: the Responses API: structured output and tools need it (Chat Completions refuses function calling on the larger
    #: GPT-6 models, and on Luna unless the effort is none)
    client_kwargs = {"use_responses_api": True}
    supports_strict = True

    def _reasoning_kwargs(self, control: str, effort: str) -> dict:
        return {"reasoning_effort": effort}

    def _off_kwargs(self, control: str, off: str, ladder: list[str]) -> dict:
        if off == ReasoningOff.NONE:
            return {"reasoning_effort": "none"}
        if off:  # cannot be turned off: as little as it can
            return {"reasoning_effort": ladder[0] if ladder else "low"}
        return {}


class OpenAICompatibleProfile(OpenAIProfile):
    kind = ProviderKind.OPENAI_COMPATIBLE
    needs_base_url = True
    client_kwargs = {}  # a vLLM or OpenRouter server speaks Chat Completions
    supports_strict = False


class GroqProfile(OpenAIProfile):
    kind = ProviderKind.GROQ
    langchain_provider = "groq"
    allowed_params = frozenset({"temperature", "max_tokens", "stop"})
    client_kwargs = {}


class AnthropicProfile(ProviderProfile):
    kind = ProviderKind.ANTHROPIC
    langchain_provider = "anthropic"
    #: from API version 2026-10-21 a request with temperature, top_p or top_k is a 400 on every model
    allowed_params = frozenset({"max_tokens", "stop"})
    #: Claude 5.x takes adaptive thinking steered by effort; a token budget is a 400
    NO_BUDGET = re.compile(r"claude-(haiku|sonnet|opus|fable|mythos)-5")

    def rejects_reasoning_control(self, model_name: str, control: str) -> str:
        if control == ReasoningControl.BUDGET_TOKENS and self.NO_BUDGET.match(model_name):
            return "Claude 5 models do not accept budget_tokens: control reasoning by effort."
        return ""

    def to_integration_kwargs(self, params: dict) -> dict:
        return super().to_integration_kwargs({k: v for k, v in params.items() if k not in SAMPLING_PARAMS})

    def _reasoning_kwargs(self, control: str, effort: str) -> dict:
        if control == ReasoningControl.BUDGET_TOKENS:
            return {"thinking": {"type": "enabled", "budget_tokens": self.budgets[effort]}}
        return {"effort": effort}

    def _off_kwargs(self, control: str, off: str, ladder: list[str]) -> dict:
        if off == ReasoningOff.DISABLED:
            return {"thinking": {"type": "disabled"}}
        if off:  # Sonnet, Opus and Fable cannot disable thinking: the lowest effort
            return {"effort": ladder[0] if ladder else "low"}
        return {}


class GoogleGenAIProfile(ProviderProfile):
    kind = ProviderKind.GOOGLE_GENAI
    langchain_provider = "google_genai"
    allowed_params = frozenset(
        {"temperature", "top_p", "top_k", "max_tokens", "stop", "seed", "presence_penalty", "frequency_penalty"}
    )

    def _reasoning_kwargs(self, control: str, effort: str) -> dict:
        if control == ReasoningControl.BUDGET_TOKENS:
            return {"thinking_budget": self.budgets[effort]}
        return {"thinking_level": effort}

    def _off_kwargs(self, control: str, off: str, ladder: list[str]) -> dict:
        if not off:
            return {}
        if control == ReasoningControl.BUDGET_TOKENS:  # a 2.5 model: a budget of 0 where it can be switched off
            return {"thinking_budget": 0 if off == ReasoningOff.MINIMAL else self.budgets["low"]}
        # `minimal` where the model has it; Gemini 3.8 Flash and Gemini 4 return an error for it, so their lowest level
        return {"thinking_level": ladder[0] if ladder else ("minimal" if off == ReasoningOff.MINIMAL else "low")}


class OllamaProfile(ProviderProfile):
    kind = ProviderKind.OLLAMA
    langchain_provider = "ollama"
    allowed_params = frozenset({"temperature", "top_p", "top_k", "max_tokens", "stop", "seed"})
    renames = {"max_tokens": "num_predict"}
    needs_base_url = True
    needs_api_key = False
    supports_client_timeout = False  # ChatOllama has neither field

    def reasoning_kwargs(self, control: str, effort: str) -> dict:
        # Ollama switches thinking on or off rather than taking a level, so "none" is an explicit False.
        if control == ReasoningControl.NONE:
            return {}
        return {"reasoning": effort != "none"}

    def _reasoning_kwargs(self, control: str, effort: str) -> dict:
        return {"reasoning": True}


class ProviderProfiles:
    """Registry: provider kind -> its profile."""

    DEFAULT_PROFILES: ClassVar[tuple[type[ProviderProfile], ...]] = (
        OpenAIProfile,
        OpenAICompatibleProfile,
        GroqProfile,
        AnthropicProfile,
        GoogleGenAIProfile,
        OllamaProfile,
    )

    def __init__(self, profiles: tuple[ProviderProfile, ...] | None = None):
        profiles = profiles if profiles is not None else tuple(cls() for cls in self.DEFAULT_PROFILES)
        self._by_kind = {profile.kind: profile for profile in profiles}

    def for_kind(self, kind: str) -> ProviderProfile:
        try:
            return self._by_kind[kind]
        except KeyError:
            raise UnknownProviderKind(f"No provider profile for kind {kind!r}") from None

    def kinds(self) -> list[str]:
        return list(self._by_kind)


# The stateless default registry shared by models, the resolver and the chat-model factory.
PROVIDER_PROFILES = ProviderProfiles()

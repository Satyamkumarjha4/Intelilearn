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

from abc import ABC, abstractmethod
from collections.abc import Mapping
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

    def reasoning_kwargs(self, control: str, effort: str) -> dict:
        """Extra chat-model kwargs for this effort; {} when reasoning is off or not controllable."""
        if effort == "none" or control == ReasoningControl.NONE:
            return {}
        return self._reasoning_kwargs(control, effort)

    @abstractmethod
    def _reasoning_kwargs(self, control: str, effort: str) -> dict:
        """The integration's parameter for an active effort (low/medium/high) under this control."""

    def apply_reasoning(self, control: str, effort: str, params: dict, *, disables_sampling: bool) -> tuple[dict, dict]:
        """Return (params, reasoning_kwargs) with sampling params removed and max_tokens raised where needed."""
        extra = self.reasoning_kwargs(control, effort)
        active = bool(extra) and extra.get("reasoning", True) is not False
        params = dict(params)
        if active and disables_sampling:
            for key in SAMPLING_PARAMS:
                params.pop(key, None)
        if "thinking" in extra:
            budget = extra["thinking"]["budget_tokens"]
            params["max_tokens"] = max(params.get("max_tokens", 0), budget + _ANSWER_HEADROOM_TOKENS)
        return params, extra


class OpenAIProfile(ProviderProfile):
    kind = ProviderKind.OPENAI
    langchain_provider = "openai"
    allowed_params = frozenset(
        {"temperature", "top_p", "max_tokens", "stop", "seed", "presence_penalty", "frequency_penalty"}
    )

    def _reasoning_kwargs(self, control: str, effort: str) -> dict:
        return {"reasoning_effort": effort}


class OpenAICompatibleProfile(OpenAIProfile):
    kind = ProviderKind.OPENAI_COMPATIBLE
    needs_base_url = True


class GroqProfile(OpenAIProfile):
    kind = ProviderKind.GROQ
    langchain_provider = "groq"
    allowed_params = frozenset({"temperature", "max_tokens", "stop"})


class AnthropicProfile(ProviderProfile):
    kind = ProviderKind.ANTHROPIC
    langchain_provider = "anthropic"
    allowed_params = frozenset({"temperature", "top_p", "top_k", "max_tokens", "stop"})

    def _reasoning_kwargs(self, control: str, effort: str) -> dict:
        if control == ReasoningControl.BUDGET_TOKENS:
            return {"thinking": {"type": "enabled", "budget_tokens": self.budgets[effort]}}
        return {"effort": effort}


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

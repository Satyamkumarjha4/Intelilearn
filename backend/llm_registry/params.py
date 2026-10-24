"""Provider-neutral parameter names used in the registry, and how each LangChain integration spells them.

Admins write canonical names (temperature, max_tokens, ...). Each provider kind accepts only the names
its integration supports (checked against the installed langchain-* packages), and a few are renamed
when the chat model is built (e.g. max_tokens -> num_predict for Ollama).
"""

from typing import Any


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


_OPENAI_PARAMS = {"temperature", "top_p", "max_tokens", "stop", "seed", "presence_penalty", "frequency_penalty"}

ALLOWED_PARAMS: dict[str, set[str]] = {
    ProviderKind.OPENAI: _OPENAI_PARAMS,
    ProviderKind.OPENAI_COMPATIBLE: _OPENAI_PARAMS,
    ProviderKind.ANTHROPIC: {"temperature", "top_p", "top_k", "max_tokens", "stop"},
    ProviderKind.GOOGLE_GENAI: {
        "temperature", "top_p", "top_k", "max_tokens", "stop", "seed", "presence_penalty", "frequency_penalty",
    },
    ProviderKind.GROQ: {"temperature", "max_tokens", "stop"},
    ProviderKind.OLLAMA: {"temperature", "top_p", "top_k", "max_tokens", "stop", "seed"},
}  # fmt: skip

SAMPLING_PARAMS = {"temperature", "top_p", "top_k"}

# init_chat_model(model_provider=...) for each kind
LANGCHAIN_PROVIDER = {
    ProviderKind.GOOGLE_GENAI: "google_genai",
    ProviderKind.GROQ: "groq",
    ProviderKind.OPENAI: "openai",
    ProviderKind.ANTHROPIC: "anthropic",
    ProviderKind.OLLAMA: "ollama",
    ProviderKind.OPENAI_COMPATIBLE: "openai",
}

_RENAMES = {ProviderKind.OLLAMA: {"max_tokens": "num_predict"}}


def validate_params(kind: str, params: Any) -> list[str]:
    """Return human-readable problems with a params dict for this provider kind (empty if fine)."""
    if not isinstance(params, dict):
        return ['Parameters must be a JSON object, e.g. {"temperature": 0.4}.']
    allowed = ALLOWED_PARAMS.get(kind, set())
    problems = []
    for key, value in params.items():
        if key not in allowed:
            problems.append(f"'{key}' is not supported for this provider; allowed: {', '.join(sorted(allowed))}.")
        elif key in {"temperature", "top_p", "presence_penalty", "frequency_penalty"} and not isinstance(
            value, int | float
        ):
            problems.append(f"'{key}' must be a number.")
        elif key in {"max_tokens", "top_k", "seed"} and (not isinstance(value, int) or value < 0):
            problems.append(f"'{key}' must be a non-negative integer.")
        elif key == "stop" and not (isinstance(value, list) and all(isinstance(s, str) for s in value)):
            problems.append("'stop' must be a list of strings.")
    return problems


def to_integration_kwargs(kind: str, params: dict) -> dict:
    renames = _RENAMES.get(kind, {})
    return {renames.get(key, key): value for key, value in params.items()}

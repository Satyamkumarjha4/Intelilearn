"""Translate a node's reasoning effort (none/low/medium/high) into each integration's own parameters.

Parameter names were checked against the installed packages:
  OpenAI / OpenAI-compatible / Groq   reasoning_effort="low|medium|high"
  Anthropic                           effort="low|medium|high"            (reasoning_control=effort)
                                      thinking={"type": "enabled", ...}    (reasoning_control=budget_tokens)
  Google Gemini                       thinking_level="low|medium|high"     (reasoning_control=effort)
                                      thinking_budget=<tokens>             (reasoning_control=budget_tokens)
  Ollama                              reasoning=True/False
"""

from django.conf import settings

from .params import SAMPLING_PARAMS, ProviderKind


class ReasoningControl:
    EFFORT = "effort"
    BUDGET_TOKENS = "budget_tokens"
    NONE = "none"

    CHOICES = [
        (EFFORT, "Effort level (low / medium / high)"),
        (BUDGET_TOKENS, "Thinking-token budget"),
        (NONE, "No reasoning control"),
    ]


def budget_for(effort: str) -> int:
    return settings.LLM_REASONING_BUDGETS[effort]


def reasoning_kwargs(kind: str, control: str, effort: str) -> dict:
    """Extra chat-model kwargs for this effort; {} when reasoning is off or not controllable."""
    if kind == ProviderKind.OLLAMA and control != ReasoningControl.NONE:
        return {"reasoning": effort != "none"}
    if effort == "none" or control == ReasoningControl.NONE:
        return {}

    if kind in (ProviderKind.OPENAI, ProviderKind.OPENAI_COMPATIBLE, ProviderKind.GROQ):
        return {"reasoning_effort": effort}
    if kind == ProviderKind.ANTHROPIC:
        if control == ReasoningControl.BUDGET_TOKENS:
            return {"thinking": {"type": "enabled", "budget_tokens": budget_for(effort)}}
        return {"effort": effort}
    if kind == ProviderKind.GOOGLE_GENAI:
        if control == ReasoningControl.BUDGET_TOKENS:
            return {"thinking_budget": budget_for(effort)}
        return {"thinking_level": effort}
    return {}


def apply_reasoning(
    kind: str, control: str, effort: str, params: dict, *, disables_sampling: bool
) -> tuple[dict, dict]:
    """Return (params, reasoning_kwargs) with sampling params removed and max_tokens raised where needed."""
    extra = reasoning_kwargs(kind, control, effort)
    active = bool(extra) and extra.get("reasoning", True) is not False
    params = dict(params)
    if active and disables_sampling:
        for key in SAMPLING_PARAMS:
            params.pop(key, None)
    # A thinking budget counts against max_tokens, so leave room for the actual answer.
    if "thinking" in extra:
        budget = extra["thinking"]["budget_tokens"]
        params["max_tokens"] = max(params.get("max_tokens", 0), budget + 4096)
    return params, extra

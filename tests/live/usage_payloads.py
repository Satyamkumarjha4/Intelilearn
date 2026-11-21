"""What one reply says about tokens, as plain JSON, read from a real provider.

Why: several facts the cost model rests on were not printed on any provider page (docs/to_be_developed/model-strategy.md
Appendix B): whether `output_tokens` includes the thinking tokens, whether `input_tokens` includes the cached ones, and
which field carries each. One real reply from each provider settles them, so `UsagePayload` writes down exactly what
LangChain and the provider returned, and `findings` lists what in it the cost code cannot read.
"""

import json

PROVIDER_USAGE_KEYS = ("token_usage", "usage", "usage_metadata")


class UsagePayload:
    @staticmethod
    def of(message) -> dict:
        """The LangChain usage and the provider's own, side by side."""
        meta = getattr(message, "response_metadata", None) or {}
        return {
            "usage_metadata": dict(getattr(message, "usage_metadata", None) or {}),
            "provider_usage": next((meta[key] for key in PROVIDER_USAGE_KEYS if meta.get(key)), None),
            "response_metadata_keys": sorted(meta),
        }

    @staticmethod
    def findings(payload: dict, *, thinking_asked: bool) -> list[str]:
        """What the cost code needs and the reply did not carry."""
        usage = payload["usage_metadata"]
        found = [f"{key} is missing or not a number" for key in ("input_tokens", "output_tokens")
                 if not isinstance(usage.get(key), int)]  # fmt: skip
        details = usage.get("output_token_details") or {}
        if thinking_asked and "reasoning" not in details:
            found.append("thinking was asked for but output_token_details.reasoning is not reported")
        return found

    @staticmethod
    def text(provider: str, model: str, payload: dict) -> str:
        return f"USAGE {provider}/{model}: {json.dumps(payload, sort_keys=True, default=str)}"

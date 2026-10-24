"""Write one ModelCall row per gateway attempt: status, latency, tokens and cost, with secrets masked."""

import logging

from .models import ModelCall
from .redaction import REDACTOR, Redactor
from .resolver import ResolvedModel

logger = logging.getLogger(__name__)


class ModelCallRecorder:
    MAX_ERROR_CHARS = 4000

    def __init__(self, redactor: Redactor = REDACTOR):
        self._redactor = redactor

    def record(
        self,
        *,
        node_key: str,
        lesson_id,
        run_id,
        model: ResolvedModel,
        fallback_index: int,
        attempt: int,
        status: str,
        latency_ms: int,
        error: str = "",
        message=None,
    ) -> None:
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        try:
            ModelCall.objects.create(
                node_key=node_key,
                lesson_id=lesson_id,
                run_id=run_id,
                provider_key=model.provider_key,
                model_name=model.model_name,
                attempt=attempt,
                fallback_index=fallback_index,
                status=status,
                error=self._redactor.redact(error)[: self.MAX_ERROR_CHARS],
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=(usage.get("output_token_details") or {}).get("reasoning"),
                tool_calls=len(getattr(message, "tool_calls", None) or []),
                cost=self.cost(model, input_tokens, output_tokens),
            )
        except Exception:  # logging must never break a generation run
            logger.exception("llm_registry: could not record model call")

    @staticmethod
    def cost(model: ResolvedModel, input_tokens: int | None, output_tokens: int | None) -> float | None:
        if input_tokens is None or output_tokens is None or model.input_cost_per_mtok is None:
            return None
        return (input_tokens * model.input_cost_per_mtok + output_tokens * (model.output_cost_per_mtok or 0)) / 1e6

"""Write one ModelCall row per gateway attempt: status, latency, tokens and cost, with secrets masked."""

import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from django.utils import timezone

from .costing import CallCosts, TokenUsage
from .models import ModelCall
from .redaction import REDACTOR, Redactor
from .resolver import ResolvedModel

logger = logging.getLogger(__name__)
ONE_MICRODOLLAR = Decimal("0.000001")


class ModelCallRecorder:
    MAX_ERROR_CHARS = 4000

    def __init__(
        self,
        redactor: Redactor = REDACTOR,
        costs: CallCosts | None = None,
        today: Callable[[], date] = lambda: timezone.now().date(),
    ):
        self._redactor = redactor
        self._costs = costs if costs is not None else CallCosts()
        self._today = today

    def record(
        self,
        *,
        node_key: str,
        lesson_id,
        run_id,
        model: ResolvedModel,
        quiz_id=None,
        fallback_index: int,
        attempt: int,
        status: str,
        latency_ms: int,
        rate_limit_wait_ms: int = 0,
        error: str = "",
        message=None,
    ) -> int | None:
        """Write the row and return its id (None when the write failed), so a refused output can be kept on it."""
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        tokens = TokenUsage.from_metadata(usage)
        try:
            cost = self._costs.cost(model, tokens, self._today())
            if cost is not None:
                cost = cost.quantize(ONE_MICRODOLLAR)  # the column keeps six decimals
            row = ModelCall.objects.create(
                node_key=node_key,
                lesson_id=lesson_id,
                run_id=run_id,
                quiz_id=quiz_id,
                provider_key=model.provider_key,
                model_name=model.model_name,
                attempt=attempt,
                fallback_index=fallback_index,
                status=status,
                error=self._redactor.redact(error)[: self.MAX_ERROR_CHARS],
                latency_ms=latency_ms,
                rate_limit_wait_ms=rate_limit_wait_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=(usage.get("output_token_details") or {}).get("reasoning"),
                cached_input_tokens=tokens.cached_input_tokens if tokens else None,
                cache_write_tokens=tokens.cache_write_tokens if tokens else None,
                tool_calls=len(getattr(message, "tool_calls", None) or []),
                cost=cost,
                cost_usd=cost,
            )
            return row.id
        except Exception:  # logging must never break a generation run
            logger.exception("llm_registry: could not record model call")
            return None

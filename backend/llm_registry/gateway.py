"""The single way graph nodes call an LLM.

For a node it walks the resolved chain (primary, then fallbacks). On each model:
  - transient errors (timeouts, 429, 5xx, connection) are retried with backoff, honouring Retry-After
  - a reply that doesn't match the schema gets one in-place repair attempt, then the next model is tried
  - fatal errors (auth, unknown model, bad request, missing key) move straight to the next model
Every attempt is logged as a ModelCall. Whether an answer is *good* is the graph's job, not the gateway's.
"""

import json
import logging
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from .models import ModelCall
from .node_specs import OutputMode
from .providers import MissingAPIKey, build_chat_model
from .ratelimit import CacheWindowRateLimiter, RateLimiter, RateLimitWaitExceeded
from .redaction import REDACTOR
from .resolver import ResolvedModel, ResolvedNode, node_from_snapshot

logger = logging.getLogger(__name__)

BACKOFF_BASE_S = 1.0
BACKOFF_MAX_S = 30.0
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
RETRYABLE_NAMES = ("Timeout", "RateLimit", "Connection", "InternalServer", "ServiceUnavailable", "Overloaded")

ChatFactory = Callable[[ResolvedModel, int], Any]
EventSink = Callable[[dict], None]


class NodeDisabled(RuntimeError):
    pass


class AllModelsFailed(RuntimeError):
    def __init__(self, node_key: str, errors: list[str]):
        errors = [REDACTOR.redact(e) for e in errors]
        self.node_key, self.errors = node_key, errors
        super().__init__(
            f"Every model for {node_key} failed: " + " | ".join(errors) if errors else f"{node_key} has no models"
        )


@dataclass
class GatewayResult:
    output: Any  # parsed Pydantic object, AIMessage (tools) or str (text)
    message: AIMessage | None
    model: ResolvedModel
    fallback_index: int
    attempts: int


def _status_code(exc: Exception) -> int | None:
    for candidate in (exc, getattr(exc, "response", None)):
        for attr in ("status_code", "status", "code"):
            value = getattr(candidate, attr, None)
            if isinstance(value, int) and 100 <= value < 600:
                return value
    return None


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, MissingAPIKey | RateLimitWaitExceeded):
        return False
    if isinstance(exc, TimeoutError | ConnectionError):
        return True
    status = _status_code(exc)
    if status is not None:
        return status in RETRYABLE_STATUS
    names = [cls.__name__ for cls in type(exc).__mro__]
    return any(marker in name for name in names for marker in RETRYABLE_NAMES)


def _retry_after(exc: Exception) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        value = headers.get("retry-after")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def backoff_delay(attempt: int, exc: Exception) -> float:
    if (hinted := _retry_after(exc)) is not None:
        return min(hinted, BACKOFF_MAX_S)
    return min(BACKOFF_BASE_S * 2 ** (attempt - 1), BACKOFF_MAX_S) * (0.5 + random.random() / 2)


def _raw_text(message: AIMessage | None) -> str:
    if message is None:
        return ""
    if message.tool_calls:
        return json.dumps([call["args"] for call in message.tool_calls])
    return message.text if hasattr(message, "text") else str(message.content)


class Gateway:
    def __init__(
        self,
        chat_factory: ChatFactory = build_chat_model,
        *,
        sleep: Callable[[float], None] = time.sleep,
        limiter: RateLimiter | None = None,
    ):
        self.chat_factory, self.sleep = chat_factory, sleep
        self.limiter = limiter if limiter is not None else CacheWindowRateLimiter()

    def invoke(
        self,
        node_key: str,
        messages: Sequence[BaseMessage],
        *,
        snapshot: dict,
        schema: type[BaseModel] | None = None,
        tools: Sequence[Any] | None = None,
        lesson_id: Any = None,
        run_id: Any = None,
        on_event: EventSink | None = None,
    ) -> GatewayResult:
        node = node_from_snapshot(snapshot, node_key)
        if not node.enabled:
            raise NodeDisabled(f"{node_key} is disabled in the registry")
        if node.output == OutputMode.STRUCTURED and schema is None:
            raise ValueError(f"{node_key} returns structured output; pass schema=")
        if node.output == OutputMode.TOOLS and not tools:
            raise ValueError(f"{node_key} is a tool-calling node; pass tools=")

        errors: list[str] = []
        for index, model in enumerate(node.chain):
            if index > 0 and on_event:
                on_event({"type": "fallback_model", "node": node_key, "model": model.label, "fallback_index": index,
                          "reason": REDACTOR.redact(errors[-1]) if errors else ""})  # fmt: skip
            result = self._try_model(
                node, model, index, list(messages), schema, tools, errors, lesson_id, run_id, on_event
            )
            if result is not None:
                return result
        raise AllModelsFailed(node_key, errors)

    def _try_model(self, node, model, index, messages, schema, tools, errors, lesson_id, run_id, on_event):
        log = dict(node_key=node.node_key, lesson_id=lesson_id, run_id=run_id, model=model, fallback_index=index)
        try:
            runnable = self._runnable(node, model, schema, tools)
        except Exception as exc:  # e.g. missing API key or unknown provider package
            errors.append(f"{model.label}: {exc}")
            _record(**log, attempt=1, status=ModelCall.Status.FATAL_ERROR, error=str(exc), latency_ms=0)
            return None

        repaired = False
        attempt = 0
        while attempt <= model.max_retries:
            attempt += 1
            started = time.perf_counter()
            try:
                self.limiter.acquire(
                    {f"provider:{model.provider_key}": model.provider_rpm, f"model:{model.label}": model.model_rpm}
                )
                reply = runnable.invoke(messages)
            except Exception as exc:
                latency = _ms(started)
                retryable = is_retryable(exc)
                status = ModelCall.Status.RETRYABLE_ERROR if retryable else ModelCall.Status.FATAL_ERROR
                _record(**log, attempt=attempt, status=status, error=repr(exc), latency_ms=latency)
                errors.append(f"{model.label}: {type(exc).__name__}: {exc}")
                if not retryable or attempt > model.max_retries:
                    return None
                if on_event:
                    on_event({"type": "retrying", "node": node.node_key, "model": model.label, "attempt": attempt + 1,
                              "reason": type(exc).__name__})  # fmt: skip
                self.sleep(backoff_delay(attempt, exc))
                continue

            latency = _ms(started)
            if node.output == OutputMode.STRUCTURED:
                raw, parsed, parse_error = reply.get("raw"), reply.get("parsed"), reply.get("parsing_error")
                if parsed is None:
                    problem = str(parse_error) if parse_error else "no structured output was returned"
                    _record(**log, attempt=attempt, status=ModelCall.Status.INVALID_OUTPUT, error=problem,
                            latency_ms=latency, message=raw)  # fmt: skip
                    errors.append(f"{model.label}: invalid output: {problem}")
                    if repaired:
                        return None
                    repaired = True
                    attempt -= 1  # the repair round doesn't use up a transport retry
                    messages = [
                        *messages,
                        AIMessage(content=_raw_text(raw) or "(empty reply)"),
                        HumanMessage(
                            content=f"Your previous reply did not match the required schema: {problem}\n"
                            "Reply again with output that matches the schema exactly."
                        ),
                    ]
                    continue
                _record(**log, attempt=attempt, status=ModelCall.Status.OK, latency_ms=latency, message=raw)
                return GatewayResult(parsed, raw, model, index, attempt)

            _record(**log, attempt=attempt, status=ModelCall.Status.OK, latency_ms=latency, message=reply)
            output = reply if node.output == OutputMode.TOOLS else _raw_text(reply)
            return GatewayResult(output, reply, model, index, attempt)
        return None

    def _runnable(self, node: ResolvedNode, model: ResolvedModel, schema, tools):
        chat = self.chat_factory(model, node.timeout_s)
        if node.output == OutputMode.STRUCTURED:
            return chat.with_structured_output(schema, method=model.structured_output_method, include_raw=True)
        if node.output == OutputMode.TOOLS:
            return chat.bind_tools(tools)
        return chat


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _record(*, node_key, lesson_id, run_id, model, fallback_index, attempt, status, latency_ms, error="", message=None):
    usage = getattr(message, "usage_metadata", None) or {}
    input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
    reasoning_tokens = (usage.get("output_token_details") or {}).get("reasoning")
    cost = None
    if input_tokens is not None and output_tokens is not None and model.input_cost_per_mtok is not None:
        cost = (input_tokens * model.input_cost_per_mtok + output_tokens * (model.output_cost_per_mtok or 0)) / 1e6
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
            error=REDACTOR.redact(error)[:4000],
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            tool_calls=len(getattr(message, "tool_calls", None) or []),
            cost=cost,
        )
    except Exception:  # logging must never break a generation run
        logger.exception("llm_registry: could not record model call")


def invoke(node_key: str, messages: Sequence[BaseMessage], **kwargs) -> GatewayResult:
    """Module-level shortcut using the real providers."""
    return Gateway().invoke(node_key, messages, **kwargs)

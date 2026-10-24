"""The single way graph nodes call an LLM (Facade).

For a node it walks the resolved chain (primary, then fallbacks: Chain of Responsibility). On each model:
  - transient errors (timeouts, 429, 5xx, connection) are retried with backoff, honouring Retry-After
  - a reply that doesn't match the schema gets one in-place repair attempt, then the next model is tried
  - fatal errors (auth, unknown model, bad request, missing key) move straight to the next model
Every attempt is logged as a ModelCall. Whether an answer is *good* is the graph's job, not the gateway's.

The collaborators are injected, with production defaults: the chat-model factory, the rate limiter, the retry
policy, the call recorder and the output adapters (one per output mode).
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

from .models import ModelCall
from .outputs import OUTPUT_ADAPTERS, OutputAdapter, OutputAdapters
from .providers import CHAT_MODEL_FACTORY, ChatModelFactory
from .ratelimit import CacheWindowRateLimiter, RateLimiter
from .recorder import ModelCallRecorder
from .redaction import REDACTOR
from .resolver import RegistrySnapshot, ResolvedModel, ResolvedNode
from .retry import ExponentialBackoffPolicy, RetryPolicy

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


@dataclass
class _Call:
    """One invoke(): what every attempt on every model shares."""

    node: ResolvedNode
    adapter: OutputAdapter
    schema: type[BaseModel] | None
    tools: Sequence[Any] | None
    lesson_id: Any
    run_id: Any
    on_event: EventSink | None
    errors: list[str]

    def emit(self, event: dict) -> None:
        if self.on_event:
            self.on_event(event)


class Gateway:
    def __init__(
        self,
        chat_factory: ChatModelFactory | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        recorder: ModelCallRecorder | None = None,
        adapters: OutputAdapters = OUTPUT_ADAPTERS,
    ):
        self.chat_factory = chat_factory if chat_factory is not None else CHAT_MODEL_FACTORY
        self.sleep = sleep
        self.limiter = limiter if limiter is not None else CacheWindowRateLimiter()
        self.retry_policy = retry_policy if retry_policy is not None else ExponentialBackoffPolicy()
        self.recorder = recorder if recorder is not None else ModelCallRecorder()
        self.adapters = adapters

    def invoke(
        self,
        node_key: str,
        messages: Sequence[BaseMessage],
        *,
        snapshot: dict | RegistrySnapshot,
        schema: type[BaseModel] | None = None,
        tools: Sequence[Any] | None = None,
        lesson_id: Any = None,
        run_id: Any = None,
        on_event: EventSink | None = None,
    ) -> GatewayResult:
        node = RegistrySnapshot.from_json(snapshot).node(node_key)
        if not node.enabled:
            raise NodeDisabled(f"{node_key} is disabled in the registry")
        adapter = self.adapters.for_mode(node.output)
        adapter.check_request(node_key, schema, tools)

        call = _Call(node, adapter, schema, tools, lesson_id, run_id, on_event, errors=[])
        for index, model in enumerate(node.chain):
            if index > 0:
                reason = REDACTOR.redact(call.errors[-1]) if call.errors else ""
                call.emit({"type": "fallback_model", "node": node_key, "model": model.label, "fallback_index": index,
                           "reason": reason})  # fmt: skip
            result = self._try_model(call, model, index, list(messages))
            if result is not None:
                return result
        raise AllModelsFailed(node_key, call.errors)

    def _try_model(self, call: _Call, model: ResolvedModel, index: int, messages: list) -> GatewayResult | None:
        def record(**fields):
            self.recorder.record(node_key=call.node.node_key, lesson_id=call.lesson_id, run_id=call.run_id,
                                 model=model, fallback_index=index, **fields)  # fmt: skip

        try:
            chat = self.chat_factory(model, call.node.timeout_s)
            runnable = call.adapter.bind(
                chat, structured_output_method=model.structured_output_method, schema=call.schema, tools=call.tools
            )
        except Exception as exc:  # e.g. missing API key or unknown provider package
            call.errors.append(f"{model.label}: {exc}")
            record(attempt=1, status=ModelCall.Status.FATAL_ERROR, error=str(exc), latency_ms=0)
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
                retryable = self.retry_policy.is_retryable(exc)
                status = ModelCall.Status.RETRYABLE_ERROR if retryable else ModelCall.Status.FATAL_ERROR
                record(attempt=attempt, status=status, error=repr(exc), latency_ms=self._ms(started))
                call.errors.append(f"{model.label}: {type(exc).__name__}: {exc}")
                if not retryable or attempt > model.max_retries:
                    return None
                call.emit({"type": "retrying", "node": call.node.node_key, "model": model.label,
                           "attempt": attempt + 1, "reason": type(exc).__name__})  # fmt: skip
                self.sleep(self.retry_policy.delay(attempt, exc))
                continue

            outcome = call.adapter.interpret(reply)
            if not outcome.ok:
                record(attempt=attempt, status=ModelCall.Status.INVALID_OUTPUT, error=outcome.problem,
                       latency_ms=self._ms(started), message=outcome.message)  # fmt: skip
                call.errors.append(f"{model.label}: invalid output: {outcome.problem}")
                retry_messages = None if repaired else call.adapter.repair_messages(messages, outcome)
                if retry_messages is None:
                    return None
                repaired = True
                attempt -= 1  # the repair round doesn't use up a transport retry
                messages = retry_messages
                continue

            record(attempt=attempt, status=ModelCall.Status.OK, latency_ms=self._ms(started), message=outcome.message)
            return GatewayResult(outcome.output, outcome.message, model, index, attempt)
        return None

    @staticmethod
    def _ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

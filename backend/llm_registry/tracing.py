"""Tracing the gateway's model calls (Strategy).

A `CallbackProvider` gives each model call its LangChain `RunnableConfig`: the callbacks that send the call to a tracing
service, a run name, tags and metadata. `NoTracing` is the default and sends nothing. `LangSmithTracing` and
`LangfuseTracing` are chosen with `LLM_TRACING`; their keys come from the environment only (the SDKs read them).

Tracing sends prompts and replies, which contain what the learner wrote, to the service chosen: it is off unless an
operator turns it on. A tracing problem never fails a model call (`SafeTracing`).
"""

import logging
import os
from collections.abc import Callable
from typing import Any, Protocol

from django.conf import settings

logger = logging.getLogger(__name__)


class TracingNotAvailable(RuntimeError):
    """The chosen tracing service cannot be used here (a missing package or setting), said in plain words."""


class CallbackProvider(Protocol):
    def config(self, *, node_key: str, model: str, lesson_id: Any, run_id: Any) -> dict:
        """A `RunnableConfig` for one model call; empty when nothing should be traced."""


class NoTracing:
    def config(self, *, node_key: str, model: str, lesson_id: Any, run_id: Any) -> dict:
        return {}


class CallDescription:
    """What every service is told about a call, apart from the callbacks themselves."""

    @staticmethod
    def of(node_key: str, model: str, lesson_id: Any, run_id: Any) -> dict:
        return {
            "run_name": node_key,
            "tags": [node_key],
            "metadata": {
                "node_key": node_key,
                "model": model,
                "lesson_id": str(lesson_id or ""),
                "run_id": str(run_id or ""),
            },
        }


class LangSmithTracing:
    """LangSmith through LangChain's own tracer. It reads `LANGSMITH_API_KEY` (and `LANGSMITH_ENDPOINT`) itself."""

    def __init__(self, project: str | None = None, tracer: Callable[..., Any] | None = None):
        self.project = project or os.environ.get("LANGSMITH_PROJECT") or "lesson-crafter"
        self._tracer = tracer

    def config(self, *, node_key: str, model: str, lesson_id: Any, run_id: Any) -> dict:
        if self._tracer is None:
            from langchain_core.tracers.langchain import LangChainTracer

            self._tracer = LangChainTracer
        return {"callbacks": [self._tracer(project_name=self.project)]} | CallDescription.of(
            node_key, model, lesson_id, run_id
        )


class LangfuseTracing:
    """Langfuse through its LangChain handler. The package is imported when first used, so it is optional: without
    it the operator is told to install it (`uv add langfuse`). It reads `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`
    and `LANGFUSE_HOST` itself."""

    def __init__(self, handler: Callable[[], Any] | None = None):
        self._handler = handler

    def config(self, *, node_key: str, model: str, lesson_id: Any, run_id: Any) -> dict:
        description = CallDescription.of(node_key, model, lesson_id, run_id)
        description["metadata"] |= {"langfuse_session_id": str(lesson_id or ""), "langfuse_tags": [node_key]}
        return {"callbacks": [self.handler()]} | description

    def handler(self) -> Any:
        if self._handler is None:
            try:
                from langfuse.langchain import CallbackHandler
            except ImportError as exc:
                raise TracingNotAvailable(
                    "LLM_TRACING=langfuse needs the `langfuse` package: add it with `uv add langfuse` and rebuild."
                ) from exc
            self._handler = CallbackHandler
        return self._handler()


class SafeTracing:
    """Wraps a provider so that tracing can never fail (or slow down for ever) a model call."""

    def __init__(self, provider: CallbackProvider):
        self.provider = provider
        self._warned = False

    def config(self, *, node_key: str, model: str, lesson_id: Any, run_id: Any) -> dict:
        try:
            return self.provider.config(node_key=node_key, model=model, lesson_id=lesson_id, run_id=run_id)
        except Exception as exc:
            if not self._warned:  # once per process: the same problem would repeat for every call
                logger.warning("Tracing is switched off for this process: %s", exc)
                self._warned = True
            return {}


class TracingProviders:
    """The tracing services by the name `LLM_TRACING` uses. A new service is a new class registered here."""

    PROVIDERS: dict[str, Callable[[], CallbackProvider]] = {
        "none": NoTracing,
        "langsmith": LangSmithTracing,
        "langfuse": LangfuseTracing,
    }

    @classmethod
    def for_name(cls, name: str) -> CallbackProvider:
        try:
            return cls.PROVIDERS[(name or "none").strip().lower()]()
        except KeyError:
            raise TracingNotAvailable(f"LLM_TRACING={name!r} is not one of {', '.join(cls.PROVIDERS)}.") from None

    @classmethod
    def from_settings(cls) -> CallbackProvider:
        """The provider the environment asks for, wrapped so it cannot fail a call; an unknown name means no tracing."""
        try:
            return SafeTracing(cls.for_name(getattr(settings, "LLM_TRACING", "none")))
        except TracingNotAvailable as exc:
            logger.warning("Tracing is off: %s", exc)
            return NoTracing()

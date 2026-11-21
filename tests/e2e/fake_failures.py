"""Failure injection for the fake LLM server: "the next call for this schema fails like this".

A real provider cannot be asked to fail on cue, and the fallback layers and the refund paths only run when a model
fails. The fake has a `FailurePlan` (rules a test or an auditor adds over HTTP, see `Handler._control`), and each call
asks the plan whether it is meant to fail. A rule names a mode; each mode is one `FailureMode` class (Strategy, one per
failure, registered in `FAILURES`), so a new failure is a new class and no `if mode ==` anywhere.

    POST /_control/fail   {"mode": "rate_limit", "schema": "DiagnosticBundle", "times": 2}
    GET  /_control/plan   the rules left and how many calls each schema had
    POST /_control/reset  forget every rule

Never reachable from production: the server only runs on the throwaway stacks, and `llm_registry.E001` refuses a
registry that points at it when DEBUG is off.
"""

import json
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Any, ClassVar, Protocol

ANY_SCHEMA = "*"


class UnknownFailure(ValueError):
    """A rule the plan will not take: the message says what to send instead."""


@dataclass(frozen=True)
class FailureRule:
    mode: str
    schema: str  # a schema name, "text" or "agent" for the calls that have none, or "*" for every call
    times: int  # calls left that fail; -1 is every call until reset
    delay_s: float  # how long the `timeout` mode keeps the caller waiting (0: the mode's default)

    def matches(self, schema: str) -> bool:
        return self.schema in (ANY_SCHEMA, schema)

    def as_dict(self) -> dict:
        return {"mode": self.mode, "schema": self.schema, "times": self.times, "delay_s": self.delay_s}


@dataclass(frozen=True)
class Reply:
    """What the server sends instead of an answer."""

    status: int
    body: dict
    headers: dict[str, str]


class Canned(Protocol):
    def rejected(self, schema: str) -> dict:
        """A reply that fits the schema and that the real validators refuse; KeyError when there is none."""


@dataclass(frozen=True)
class FailureContext:
    request: dict
    schema: str
    canned: Canned
    rule: FailureRule


class FailureMode(ABC):
    name: ClassVar[str]

    @abstractmethod
    def respond(self, context: FailureContext) -> Reply | None:
        """The failing reply, or None when the caller is meant to be left waiting (the server then closes the line)."""

    @staticmethod
    def error(status: int, message: str, kind: str, code: str, headers: dict[str, str] | None = None) -> Reply:
        body = {"error": {"message": message, "type": kind, "code": code}}
        return Reply(status, body, headers or {})

    @staticmethod
    def completion(request: dict, text: str, schema: str) -> Reply:
        """A 200 chat completion carrying `text`, as a tool call when the request forced a function (as the server's own
        replies are)."""
        message: dict[str, Any] = {"role": "assistant", "content": text}
        finish = "stop"
        if request.get("tools"):
            call = {
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {"name": schema, "arguments": text},
            }
            message, finish = {"role": "assistant", "content": None, "tool_calls": [call]}, "tool_calls"
        body = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": 0,
            "model": request.get("model", "fake-model"),
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": len(text) // 4, "total_tokens": 100 + len(text) // 4},
        }
        return Reply(200, body, {})


class InvalidJson(FailureMode):
    """A reply cut off in the middle, as a model that ran out of tokens or lost its way writes it."""

    name = "invalid_json"

    def respond(self, context: FailureContext) -> Reply | None:
        return self.completion(context.request, '{"truncated": [{"id": "q1", "question": "Which of', context.schema)


class RejectedOutput(FailureMode):
    """A reply that fits the schema and that the validators refuse: the graph's own retry and fallback run, not the
    gateway's."""

    name = "rejected"

    def respond(self, context: FailureContext) -> Reply | None:
        try:
            payload = context.canned.rejected(context.schema)
        except KeyError:
            return self.error(
                400,
                f"The fake LLM has no rejected variant for {context.schema!r}.",
                "invalid_request_error",
                "no_rejected_variant",
            )
        return self.completion(context.request, json.dumps(payload), context.schema)


class Timeout(FailureMode):
    """The line stays open and nothing comes, for longer than the caller's timeout."""

    name = "timeout"
    DEFAULT_DELAY_S = 90.0

    def respond(self, context: FailureContext) -> Reply | None:
        time.sleep(context.rule.delay_s or self.DEFAULT_DELAY_S)
        return None


class RateLimited(FailureMode):
    """429 with Retry-After. The message does not say a daily quota is spent, so the gateway retries it."""

    name = "rate_limit"

    def respond(self, context: FailureContext) -> Reply | None:
        return self.error(
            429,
            "Rate limit reached for requests; please retry shortly.",
            "rate_limit_error",
            "rate_limit_exceeded",
            {"Retry-After": "1"},
        )


class Unauthorized(FailureMode):
    """401: a key the provider refuses. Fatal for the gateway, and it opens the provider's breaker."""

    name = "unauthorized"

    def respond(self, context: FailureContext) -> Reply | None:
        return self.error(401, "Incorrect API key provided.", "invalid_request_error", "invalid_api_key")


class FailureModes:
    """The modes by name."""

    def __init__(self, *modes: FailureMode):
        self._modes = {mode.name: mode for mode in modes}

    def __iter__(self):
        return iter(sorted(self._modes))

    def __contains__(self, name: object) -> bool:
        return name in self._modes

    def __getitem__(self, name: str) -> FailureMode:
        return self._modes[name]


FAILURES = FailureModes(InvalidJson(), RejectedOutput(), Timeout(), RateLimited(), Unauthorized())


class FailurePlan:
    """The rules, in the order they were added; the first rule that matches a call is the one that fires.

    Thread-safe: the server answers each request on its own thread.
    """

    def __init__(self, modes: FailureModes = FAILURES):
        self._modes = modes
        self._rules: list[FailureRule] = []
        self._calls: dict[str, int] = {}
        self._failed: dict[str, int] = {}
        self._lock = threading.Lock()

    def add(self, mode: str, *, schema: str = ANY_SCHEMA, times: Any = 1, delay_s: Any = 0) -> FailureRule:
        if mode not in self._modes:
            raise UnknownFailure(f"Unknown failure mode {mode!r}; use one of: {', '.join(self._modes)}.")
        if isinstance(times, bool) or not isinstance(times, int) or not (times == -1 or times > 0):
            raise UnknownFailure(f"times must be a whole number above 0, or -1 for every call; got {times!r}.")
        if isinstance(delay_s, bool) or not isinstance(delay_s, int | float) or delay_s < 0:
            raise UnknownFailure(f"delay_s must be a number of seconds, 0 or more; got {delay_s!r}.")
        rule = FailureRule(mode, schema, times, delay_s)
        with self._lock:
            self._rules.append(rule)
        return rule

    def take(self, schema: str) -> FailureRule | None:
        """Count the call, and return the rule that makes it fail (using up one of its times), or None."""
        with self._lock:
            self._calls[schema] = self._calls.get(schema, 0) + 1
            for index, rule in enumerate(self._rules):
                if not rule.matches(schema):
                    continue
                if rule.times == 1:
                    del self._rules[index]
                elif rule.times > 1:
                    self._rules[index] = replace(rule, times=rule.times - 1)
                self._failed[schema] = self._failed.get(schema, 0) + 1
                return rule
        return None

    def reset(self) -> None:
        with self._lock:
            self._rules.clear()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "rules": [rule.as_dict() for rule in self._rules],
                "calls": dict(self._calls),
                "failed": dict(self._failed),
            }

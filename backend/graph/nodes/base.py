"""The skeletons graph nodes are built from (Template Method).

A node instance is the callable LangGraph registers: `graph.add_node(node.name, node)`. `Node.__call__` unpacks the
runtime context, announces the node, and calls `run`, so subclasses contain only their own logic.

Side effects and `interrupt()` never mix: LangGraph re-runs an interrupted node from the top when the thread
resumes, so everything with side effects goes in a `PublishNode` *before* the `AwaitNode` that only waits.
"""

import threading
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from django.db import connections
from langgraph.types import interrupt
from pydantic import BaseModel

from lessons.models import Lesson, Stage

from ..context import FlowContext, NodeBudget
from ..prompts import Prompt
from ..validators import Validator


class Node(ABC):
    name: ClassVar[str]
    #: The stage the lesson is in while this node works. A node that runs while the lesson is `failed` means a
    #: retry resumed here, so the lesson goes back to this stage without the node having to know about retries.
    stage: ClassVar[Stage | None] = None

    def __call__(self, state: dict, runtime) -> Any:
        ctx: FlowContext = runtime.context
        if self.stage:
            Lesson.objects.filter(pk=state["lesson_id"], stage=Stage.FAILED).update(stage=self.stage, error="")
        ctx.events({"type": "node", "node": self.name, "status": "running"})
        try:
            return self.run(state, ctx)
        finally:
            self.release_connection()

    @staticmethod
    def release_connection() -> None:
        """LangGraph runs nodes on pool threads. A thread's database connection belongs to no request, so nothing
        else would close it, and every run would leave connections behind."""
        if threading.current_thread() is not threading.main_thread():
            connections.close_all()

    @abstractmethod
    def run(self, state: dict, ctx: FlowContext) -> Any:
        """The state update (a dict), or a `Command` when the node also chooses where to go next."""

    @staticmethod
    def lesson(state: dict) -> Lesson:
        return Lesson.objects.get(pk=state["lesson_id"])

    @staticmethod
    def feedback(state: dict, key: str) -> list[str]:
        return list((state.get("feedback") or {}).get(key) or [])

    @staticmethod
    def attempts(state: dict, key: str) -> int:
        return (state.get("attempts") or {}).get(key, 0)


class LLMNode(Node):
    """prompt → gateway → state update. Subclasses say which prompt and schema, and how the output becomes state."""

    node_key: ClassVar[str]  # the registry node key (llm_registry/node_specs.py)
    prompt: ClassVar[Prompt]
    schema: ClassVar[type[BaseModel] | None] = None
    feedback_key: ClassVar[str | None] = None  # where the validator's problems for a retry are kept in the state

    def run(self, state: dict, ctx: FlowContext) -> dict:
        self.before(state)
        feedback = self.feedback(state, self.feedback_key) if self.feedback_key else None
        messages = self.prompt.messages(self.subject(state), feedback)
        result = ctx.invoke(state, self.node_key, messages, schema=self.schema)
        return self.to_state(result.output, state)

    def before(self, state: dict) -> None:
        """Hook for side effects that must happen before the call (for example setting the lesson stage)."""

    def subject(self, state: dict) -> dict:
        return state

    @abstractmethod
    def to_state(self, output: Any, state: dict) -> dict: ...


class ValidateNode(Node):
    """Checks the previous node's output and records the verdict as `feedback[feedback_key]`.

    When the attempts for `node_key` run out, it sets `error` so the router sends the run to `mark_failed`; a retry
    then resumes at `retry_node` with the attempt counters in `retry_keys` reset.
    """

    node_key: ClassVar[str]  # whose attempt budget applies
    feedback_key: ClassVar[str]
    retry_node: ClassVar[str]
    label: ClassVar[str]  # for the error message: "The diagnostic quiz"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        problems = self.validator(state, ctx).validate(self.subject(state), **self.context(state))
        return self.outcome(state, problems, ctx)

    @abstractmethod
    def validator(self, state: dict, ctx: FlowContext) -> Validator: ...

    @abstractmethod
    def subject(self, state: dict) -> Any: ...

    def context(self, state: dict) -> dict:
        return {}

    def outcome(self, state: dict, problems: list[str], ctx: FlowContext) -> dict:
        update: dict = {"feedback": {self.feedback_key: problems}}
        if not problems:
            return update
        attempts = self.attempts(state, self.feedback_key)
        if attempts >= NodeBudget.of(state, self.node_key).max_attempts:
            summary = "; ".join(problems[:4]) + (" …" if len(problems) > 4 else "")
            update |= {
                "error": f"{self.label} still failed its checks after {attempts} attempts: {summary}",
                "failed_node": self.retry_node,
                "retry_keys": [self.feedback_key],
            }
        else:
            ctx.events({"type": "attempt", "node": self.retry_node, "attempt": attempts + 1, "reason": problems[0]})
        return update


class PublishNode(Node):
    """The side effects before a pause: save what the learner needs to see and move the lesson to its waiting stage."""

    def run(self, state: dict, ctx: FlowContext) -> dict:
        return self.publish(state, ctx)

    @abstractmethod
    def publish(self, state: dict, ctx: FlowContext) -> dict: ...


class AwaitNode(Node):
    """Pauses until the learner answers. No side effects: this node runs again from the top on resume."""

    kind: ClassVar[str]  # shown in the `awaiting_input` event
    result_key: ClassVar[str]  # the state key that receives the resume value

    def run(self, state: dict, ctx: FlowContext) -> dict:
        value = interrupt({"kind": self.kind, **self.payload(state)})
        return {self.result_key: self.accept(value)}

    def payload(self, state: dict) -> dict:
        return {}

    def accept(self, value: Any) -> Any:
        return value

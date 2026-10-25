"""When a run gives up: record why, then wait for the learner to press Retry."""

from langgraph.types import Command, interrupt

from lessons.models import Lesson

from ..context import FlowContext
from .base import Node


class MarkFailedNode(Node):
    """The side effect of a failure. `AwaitRetryNode` (after it) only pauses, because it re-runs on resume."""

    name = "mark_failed"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        message = state.get("error") or "The lesson could not be built."
        Lesson.objects.get(pk=state["lesson_id"]).fail(message)
        return {}


class AwaitRetryNode(Node):
    """Paused until `POST /lessons/{id}/retry` resumes the thread, then re-runs the node that gave up."""

    name = "await_retry"

    def run(self, state: dict, ctx: FlowContext) -> Command:
        interrupt({"kind": "retry", "message": state.get("error") or ""})
        keys = state.get("retry_keys") or []
        return Command(
            goto=state.get("failed_node") or "load_context",
            update={
                "error": None,
                "failed_node": None,
                "retry_keys": [],
                "attempts": dict.fromkeys(keys),  # None resets the count (Reducers.merge_counts)
            },
        )

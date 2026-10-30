"""Finding lesson threads that a release left pointing at nothing.

A lesson can wait at a quiz for days. When a release removes or renames a graph node, a thread that waits at it (or
would resume into it after a Retry) is stranded, and LangGraph hides that: the compiled graph shows no pending step, and
resuming quietly ends the run. So the check reads the raw checkpoint. The deploy notes say stranded threads are drained:
`manage.py stranded_threads` lists them and `--mark-failed` ends them with a message the learner can act on.
"""

from collections.abc import Callable
from dataclasses import dataclass

from .checkpoints import CheckpointerFactory
from .models import Lesson, Stage


class PendingNodes:
    """What a checkpoint is about to run, read from the checkpoint itself."""

    TRIGGER = "branch:to:"
    TASKS = "__pregel_tasks"
    RETRY_PAUSE = "await_retry"

    def of(self, checkpoint: dict) -> set[str]:
        """The nodes whose trigger channel still holds its signal (a consumed one is dropped from the checkpoint), and
        the nodes a `Send` is waiting to start."""
        values = checkpoint.get("channel_values") or {}
        pending = {channel.removeprefix(self.TRIGGER) for channel in values if channel.startswith(self.TRIGGER)}
        for send in values.get(self.TASKS) or []:
            if node := getattr(send, "node", None):
                pending.add(node)
        return pending

    def resumes_into(self, checkpoint: dict) -> str | None:
        """Where a thread paused at the retry pause goes when it is resumed: the node that gave up."""
        if self.RETRY_PAUSE not in self.of(checkpoint):
            return None
        return (checkpoint.get("channel_values") or {}).get("failed_node") or None


@dataclass(frozen=True)
class StrandedThread:
    lesson_id: object
    topic: str
    stage: str
    missing: tuple[str, ...]  # the nodes the thread needs and the graph no longer has


class StrandedThreads:
    #: said to the learner, so it names no node: a lesson started before an update cannot be carried on
    MESSAGE = (
        "This lesson was started before an update and cannot be carried on. Please delete it and start a new lesson."
    )

    def __init__(
        self,
        checkpointers: CheckpointerFactory | None = None,
        node_names: Callable[[], set[str]] | None = None,
        pending: PendingNodes | None = None,
    ):
        self.checkpointers = checkpointers or CheckpointerFactory()
        self.node_names = node_names or self.current_nodes
        self.pending = pending or PendingNodes()

    @staticmethod
    def current_nodes() -> set[str]:
        from graph.builders import FlowGraphBuilder  # the builders import the nodes, which import this app's models

        return set(FlowGraphBuilder().build().nodes)

    def find(self) -> list[StrandedThread]:
        known = self.node_names()
        found = []
        with self.checkpointers.saver() as saver:
            for lesson in Lesson.objects.exclude(stage=Stage.READY).order_by("created_at").iterator():
                checkpoint = self._checkpoint(saver, lesson)
                if checkpoint is None:
                    continue
                needed = self.pending.of(checkpoint)
                if target := self.pending.resumes_into(checkpoint):
                    needed.add(target)
                if missing := tuple(sorted(needed - known)):
                    found.append(StrandedThread(lesson.pk, lesson.topic, lesson.stage, missing))
        return found

    @staticmethod
    def _checkpoint(saver, lesson: Lesson) -> dict | None:
        entry = saver.get_tuple({"configurable": {"thread_id": str(lesson.pk)}})
        return entry.checkpoint if entry else None

    def mark_failed(self, stranded: list[StrandedThread]) -> int:
        """End each lesson with `MESSAGE`. A lesson that is no longer open (ready, or already failed) is left alone.
        → how many were changed."""
        changed = 0
        for thread in stranded:
            lesson = Lesson.objects.filter(pk=thread.lesson_id).exclude(stage__in=[Stage.READY, Stage.FAILED]).first()
            if lesson is not None:
                lesson.fail(self.MESSAGE)
                changed += 1
        return changed

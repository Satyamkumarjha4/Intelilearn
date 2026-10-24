"""Executes one `GraphRun`: the seam between the web app (views, Celery tasks) and the LangGraph threads.

`FlowRunner.execute(run_id)` streams the run's graph on the lesson's thread, publishes progress, and ends the run as
paused (waiting for the learner), succeeded, failed or cancelled. Everything it needs is injected, so tests run it
with a scripted gateway, an in-memory checkpointer and a list for a publisher.
"""

import logging
from collections.abc import Callable

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from langgraph.types import Command

from graph.context import FlowContext, default_context
from graph.errors import RunFailed
from graph.registry import GraphRegistry, UnknownGraph
from graph.sandbox import SandboxError
from llm_registry.gateway import AllModelsFailed, NodeDisabled

from .checkpoints import CheckpointerFactory
from .effects import RunEffects
from .events import EventPublisher, RedisEventPublisher, RunEvent, RunEventTranslator
from .models import GraphRun, Lesson

logger = logging.getLogger(__name__)


class FailureMessage:
    """A readable reason for the learner. Unexpected errors are named by type only: details may be internal."""

    def of(self, exc: Exception) -> str:
        if isinstance(exc, AllModelsFailed):
            return (
                f"Every AI model for the step '{exc.node_key}' failed. Check the model registry in the admin "
                f"and the API keys, then press Retry. Details: {exc}"
            )
        if isinstance(exc, NodeDisabled):
            return f"A step is switched off: {exc}. Bind a model to it in the model registry, then press Retry."
        if isinstance(exc, SandboxError):
            return f"The code sandbox could not run: {exc}"
        if isinstance(exc, UnknownGraph):
            return str(exc.args[0])
        if isinstance(exc, RunFailed):
            return str(exc)
        return f"Something went wrong while building the lesson ({type(exc).__name__}). Press Retry."


class GraphRunRecorder:
    """Keeps the `GraphRun` row in step with the stream. Every transition is conditional, so a cancel always wins."""

    ACTIVE = (GraphRun.Status.QUEUED, GraphRun.Status.RUNNING)

    def begin(self, run: GraphRun) -> bool:
        """QUEUED → RUNNING (a redelivered RUNNING run stays so). False when the run was cancelled meanwhile."""
        moved = GraphRun.objects.filter(pk=run.pk, status__in=self.ACTIVE).update(
            status=GraphRun.Status.RUNNING, started_at=run.started_at or timezone.now()
        )
        run.refresh_from_db()
        return bool(moved)

    def record(self, run: GraphRun, event: RunEvent) -> None:
        if event.name != "node":
            return
        run.node_status = {**run.node_status, event.data["node"]: event.data["status"]}
        GraphRun.objects.filter(pk=run.pk).update(node_status=run.node_status)

    def is_cancelled(self, run: GraphRun) -> bool:
        return GraphRun.objects.filter(pk=run.pk, status=GraphRun.Status.CANCELLED).exists()

    def finish(self, run: GraphRun, status: GraphRun.Status, error: str = "") -> None:
        GraphRun.objects.filter(pk=run.pk, status=GraphRun.Status.RUNNING).update(
            status=status, error=error, finished_at=timezone.now()
        )
        run.refresh_from_db()


class RunLock:
    """One worker per run. The lock expires, so a run whose worker died is picked up again after the TTL."""

    def __init__(self, ttl_s: int | None = None):
        self.ttl_s = ttl_s if ttl_s is not None else settings.FLOW_RUN_LOCK_TTL_S

    @staticmethod
    def key(run_id) -> str:
        return f"flow-run-lock:{run_id}"

    def acquire(self, run_id) -> bool:
        return cache.add(self.key(run_id), "1", self.ttl_s)

    def refresh(self, run_id) -> None:
        cache.touch(self.key(run_id), self.ttl_s)

    def release(self, run_id) -> None:
        cache.delete(self.key(run_id))


class FlowRunner:
    def __init__(
        self,
        graphs: GraphRegistry | None = None,
        checkpointers: CheckpointerFactory | None = None,
        events: EventPublisher | None = None,
        context_factory: Callable[..., FlowContext] | None = None,
        recorder: GraphRunRecorder | None = None,
        lock: RunLock | None = None,
        failures: FailureMessage | None = None,
        translator: RunEventTranslator | None = None,
        effects: RunEffects | None = None,
    ):
        self.graphs = graphs or GraphRegistry()
        self.checkpointers = checkpointers or CheckpointerFactory()
        self.events = events or RedisEventPublisher()
        self.context_factory = context_factory or (lambda run_id: default_context(run_id=run_id))
        self.recorder = recorder or GraphRunRecorder()
        self.lock = lock or RunLock()
        self.failures = failures or FailureMessage()
        self.translator = translator or RunEventTranslator()
        self.effects = effects or RunEffects()

    def execute(self, run_id) -> GraphRun:
        run = GraphRun.objects.select_related("lesson").get(pk=run_id)
        if run.status not in GraphRunRecorder.ACTIVE or not self.lock.acquire(run.id):
            return run  # already finished, or another worker has it
        try:
            if self.recorder.begin(run):
                self._execute(run)
        finally:
            self.lock.release(run.id)
        return run

    def _execute(self, run: GraphRun) -> None:
        try:
            interrupt = self._stream(run)
        except Exception as exc:
            logger.exception("Run %s failed", run.id)
            self._fail(run, self.failures.of(exc))
            return
        if self.recorder.is_cancelled(run):
            self.effects.on_stopped(run, "Cancelled before it finished.")
            self._publish(run, RunEvent("cancelled", {}))
            return
        lesson = Lesson.objects.get(pk=run.lesson_id)
        if interrupt is None:
            self.recorder.finish(run, GraphRun.Status.SUCCEEDED)
            self._publish(run, RunEvent("done", {"lesson_id": str(lesson.id), "stage": lesson.stage}))
        elif interrupt.get("kind") == "retry":  # the graph gave up and recorded why on the lesson
            self._fail(run, lesson.error, lesson_already_failed=True)
        else:
            self.recorder.finish(run, GraphRun.Status.PAUSED)
            self._publish(run, RunEvent("awaiting_input", {k: v for k, v in interrupt.items() if k != "message"}))

    def _stream(self, run: GraphRun) -> dict | None:
        """Run the graph until it ends or pauses. → the interrupt payload when it paused, else None."""
        graph_name = run.graph
        with self.checkpointers.saver() as saver:
            graph = self.graphs.builder(graph_name).build(saver)
            config = {"configurable": {"thread_id": self.thread_id(run)}}
            payload = self._input(graph, run, config)
            if payload is not self.NOTHING_TO_DO:
                context = self.context_factory(run_id=str(run.id))
                for mode, chunk in graph.stream(payload, config, context=context, stream_mode=["updates", "custom"]):
                    self.lock.refresh(run.id)
                    for event in self.translator.translate(mode, chunk):
                        self.recorder.record(run, event)
                        self._publish(run, event)
                    if self.recorder.is_cancelled(run):
                        return None
            interrupts = graph.get_state(config).interrupts
            return dict(interrupts[0].value) if interrupts else None

    NOTHING_TO_DO = object()

    def _input(self, graph, run: GraphRun, config: dict):
        """What to feed the thread: a resume value if it waits at an interrupt, nothing if it was interrupted by a
        crash (it continues from its checkpoint), the first input for a new thread."""
        snapshot = graph.get_state(config)
        if snapshot.interrupts:
            return Command(resume=run.payload.get("resume", True))
        if snapshot.next:
            return None
        if snapshot.values:
            return self.NOTHING_TO_DO  # the thread already ran to its end (a redelivered task)
        return {"lesson_id": str(run.lesson_id), **run.payload.get("input", {})}

    @staticmethod
    def thread_id(run: GraphRun) -> str:
        """The main flow is one thread per lesson; the small graphs get a fresh thread per run."""
        return str(run.lesson_id) if run.graph == GraphRun.Graph.FLOW else f"{run.lesson_id}:{run.id}"

    def _fail(self, run: GraphRun, message: str, *, lesson_already_failed: bool = False) -> None:
        if run.graph == GraphRun.Graph.FLOW and not lesson_already_failed:
            Lesson.objects.get(pk=run.lesson_id).fail(message)
        self.effects.on_stopped(run, message)
        self.recorder.finish(run, GraphRun.Status.FAILED, message)
        self._publish(run, RunEvent("error", {"message": message, "code": "failed"}))

    def _publish(self, run: GraphRun, event: RunEvent) -> None:
        self.events.publish(run.id, event)

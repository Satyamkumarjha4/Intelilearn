"""Runs for the console: the list, one run's detail with its timeline and model calls, and the staff actions.

Every action reuses the learner's own services (`LessonService.retry`, `LessonService.cancel`), so a staff member is
held to the same rules as the learner's button. A `GraphRun` is one Celery execution segment of a graph
(lessons/models.py).
"""

import importlib
import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from django.db import transaction
from django.db.models import Count, DecimalField, OuterRef, Q, QuerySet, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from console.audit import AuditTrail
from console.errors import NotRetryable
from console.outcomes import CallOutcomes
from lessons.models import GraphRun
from lessons.services import LessonService, has_active_run
from lessons.stages import Stage
from llm_registry.models import ModelCall


class RunQuery:
    """The runs the list shows, with each run's lesson, learner, call count and cost fetched in the one query."""

    def queryset(self, *, statuses=(), graphs=(), search="") -> QuerySet[GraphRun]:
        calls = ModelCall.objects.filter(run_id=OuterRef("pk")).order_by().values("run_id")
        runs = GraphRun.objects.select_related("lesson__owner").annotate(
            call_count=Coalesce(Subquery(calls.annotate(n=Count("id")).values("n")), 0),
            cost_sum=Coalesce(
                Subquery(calls.annotate(total=Sum("cost")).values("total")), Decimal(0), output_field=DecimalField()
            ),
        )
        if statuses:
            runs = runs.filter(status__in=statuses)
        if graphs:
            runs = runs.filter(graph__in=graphs)
        if search := search.strip():
            runs = runs.filter(
                Q(lesson__topic__icontains=search)
                | Q(lesson__owner__name__icontains=search)
                | Q(lesson__owner__email__icontains=search)
            )
        return runs

    def get(self, run_id: str) -> GraphRun | None:
        try:
            pk = uuid.UUID(run_id)
        except ValueError:
            return None
        return self.queryset().filter(pk=pk).first()


class TimelinePhase(StrEnum):
    DIAGNOSE = "diagnose"
    AUTHOR = "author"
    BUILD = "build"
    POST = "post"
    OTHER = "other"


class NodePhases:
    """The phase of the lesson a graph node belongs to, read from the code module that defines it (so a new node is
    placed by where it is written, with nothing to keep in step): diagnose, author, build, post (after the lesson is
    built: repairs and grading) or other (failure handling, or a name no node has)."""

    MODULES = {
        "diagnose": TimelinePhase.DIAGNOSE, "mastery": TimelinePhase.DIAGNOSE, "author": TimelinePhase.AUTHOR,
        "authoring_media": TimelinePhase.AUTHOR, "media_agent": TimelinePhase.AUTHOR, "build": TimelinePhase.BUILD,
        "repair": TimelinePhase.POST, "grading": TimelinePhase.POST, "failure": TimelinePhase.OTHER,
    }  # fmt: skip
    OTHER = TimelinePhase.OTHER

    def __init__(self):
        self._by_name: dict[str, TimelinePhase] | None = None

    def of(self, node: str) -> str:
        return str(self._table().get(node, self.OTHER))

    def _table(self) -> dict[str, TimelinePhase]:
        if self._by_name is None:  # imported on first use: the graph package is heavy and the list does not need it
            from graph.nodes.base import Node

            for module in self.MODULES:
                importlib.import_module(f"graph.nodes.{module}")
            self._by_name = {
                cls.name: self.MODULES.get(cls.__module__.rsplit(".", 1)[-1], self.OTHER)
                for cls in self._subclasses(Node)
                if "name" in vars(cls)
            }
        return self._by_name

    def _subclasses(self, cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from self._subclasses(sub)


class RunTimeline:
    """The steps of a run laid out in time, from what the node-status writer kept on the run (`node_status` and
    `node_timings`, lessons/runner.py), oldest first.

    * `start_offset_s` is seconds from when the run started (or was created, if it never started), never negative;
      `duration_s` is from a step's first start to its last finish.
    * `state`: `failed` if the step failed or was skipped after failing; else `waiting` if the run is paused and this
      is the step it paused in (it is waiting for the learner, so it has no duration); else `retried` if the graph ran
      the step again after its output failed a check; else `ran`. A step still running has its time so far.
    * Steps with no kept timing (a run from before timings were kept) still appear, after the timed ones, without times.
    * Model-level retries and fallbacks are not here: each model call row says its attempt and fallback_index.
    """

    FAILED = frozenset({"failed", "degraded"})

    def __init__(self, phases: NodePhases | None = None, now: Callable[[], datetime] = timezone.now):
        self._phases, self._now = phases or NodePhases(), now

    def of(self, run: GraphRun) -> list[dict]:
        origin = run.started_at or run.created_at
        steps = [self._step(run, node, status, origin) for node, status in run.node_status.items()]
        # sorted() is stable, so steps without a start keep the order they were first seen in
        steps.sort(key=lambda step: (step["start_offset_s"] is None, step["start_offset_s"] or 0))
        return steps

    def _step(self, run: GraphRun, node: str, status: str, origin: datetime) -> dict:
        timing = run.node_timings.get(node) or {}
        started = self._parse(timing.get("started_at"))
        finished = self._parse(timing.get("finished_at"))
        waiting = run.status == GraphRun.Status.PAUSED and status == "running"
        return {
            "node": node,
            "phase": self._phases.of(node),
            "start_offset_s": None if started is None else max(0.0, (started - origin).total_seconds()),
            "duration_s": self._duration(started, finished, waiting, run),
            "state": self._state(status, waiting, timing.get("retries", 0)),
        }

    def _duration(self, started, finished, waiting: bool, run: GraphRun) -> float | None:
        if started is None or waiting:
            return None
        if finished is None:
            finished = self._now() if run.is_active else None
        return None if finished is None else max(0.0, (finished - started).total_seconds())

    def _state(self, status: str, waiting: bool, retries: int) -> str:
        if status in self.FAILED:
            return "failed"
        if waiting:
            return "waiting"
        return "retried" if retries else "ran"

    @staticmethod
    def _parse(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None


class RunDetail:
    """One run as the detail page shows it: the list row's fields, the error, the timeline and the last model calls."""

    CALLS = 20

    def __init__(self, timeline: RunTimeline | None = None):
        self._timeline = timeline or RunTimeline()

    def of(self, run: GraphRun) -> GraphRun:
        """The run, with `timeline`, `recent_calls`, `can_retry` and `can_cancel` set on it for the serializer."""
        calls = ModelCall.objects.filter(run_id=run.id).order_by("-created_at", "-id")[: self.CALLS]
        run.timeline = self._timeline.of(run)
        run.recent_calls = [self._call(call) for call in calls]
        run.can_retry = RunActions.can_retry(run)
        run.can_cancel = run.is_active
        return run

    @staticmethod
    def _call(call: ModelCall) -> dict:
        return {
            "id": call.id,
            "created_at": call.created_at,
            "node": call.node_key,
            "provider": call.provider_key,
            "model": call.model_name,
            "attempt": call.attempt,
            "fallback_index": call.fallback_index,
            "status": call.status,
            "outcome": CallOutcomes.name_of(call.status, call.attempt),
            "latency_s": round(call.latency_ms / 1000, 3),
            "tokens_in": call.input_tokens,
            "tokens_out": call.output_tokens,
            "tool_calls": call.tool_calls,
            "cost": call.cost,
            "error": call.error,
        }


class RunActions:
    """Retry and cancel, as staff. Both go through `LessonService`, so the learner's rules apply, and both leave an
    audit entry once they have worked."""

    def __init__(self, trail: AuditTrail, lessons: LessonService | None = None):
        self._trail = trail
        self._lessons = lessons or LessonService()

    @staticmethod
    def can_retry(run: GraphRun) -> bool:
        """What `retry` would accept: a lesson build, of a failed lesson that has no run in progress."""
        return run.graph == GraphRun.Graph.FLOW and run.lesson.stage == Stage.FAILED and not has_active_run(run.lesson)

    def retry(self, run: GraphRun) -> GraphRun:
        """Resume the failed lesson from its checkpoint with a new run. Not in a transaction: the run is queued for a
        worker as soon as it exists, and the worker has to find it."""
        if run.graph != GraphRun.Graph.FLOW:
            raise NotRetryable()
        new = self._lessons.retry(run.lesson)
        self._trail.record(
            "run.retry", "run", run.id,
            before={"status": run.status, "lesson_stage": run.lesson.stage},
            after={"new_run_id": str(new.id), "lesson_id": str(run.lesson_id)},
        )  # fmt: skip
        return new

    def cancel(self, run: GraphRun) -> GraphRun:
        before = {"status": run.status, "lesson_stage": run.lesson.stage}
        with transaction.atomic():
            self._lessons.cancel(run)
            run.refresh_from_db()
            self._trail.record("run.cancel", "run", run.id, before=before, after={"status": run.status})
        return run

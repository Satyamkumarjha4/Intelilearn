"""The seam that lets a later pricing feature say yes or no to work that costs model calls, and learn how it ended.

Nothing here prices anything. Every action that starts paid work is named in `MeteredAction`; a service asks the
`ActionGate` before it creates a row or queues a run (`ActionMetering.authorize`), the answer travels with the run, and
`AuthorizationSettlement` tells the gate how the work ended once the action's `CompletionPoint` is reached or the run
dies first. The default gate (`OpenGate`) allows everything and stores nothing, so the app behaves as if this did not
exist. See docs/archive/modular-lessons-implementation-plan.md §5.5 and §6.7.
"""

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Protocol

from django.conf import settings
from django.db import transaction
from django.utils.module_loading import import_string
from rest_framework import status

from .errors import LessonError
from .models import GraphRun
from .stages import Stage
from .subjects import RunSubject

logger = logging.getLogger(__name__)


class MeteredAction(StrEnum):
    """Every action that starts paid model work, each with a completion point in `CompletionPoints.TABLE`."""

    LESSON_CREATE = "lesson.create"
    LESSON_CONTINUE = "lesson.continue"
    LESSON_FOLLOWUP = "lesson.followup"
    TEST_RETAKE = "test.retake"
    QUIZ_CREATE = "quiz.create"
    QUIZ_RETAKE = "quiz.retake"
    SHEET_GENERATE = "sheet.generate"


class RunOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CompletionPoint:
    """Where an action counts as done. A run can pause halfway (a quiz waits for the learner), so the end of a run is
    the wrong moment to settle: the action is complete at a lesson stage, or when its run has ended."""

    STAGE: ClassVar[str] = "stage"
    RUN_END: ClassVar[str] = "run_end"

    kind: str
    stage: str = ""

    @classmethod
    def at_stage(cls, stage: str) -> "CompletionPoint":
        return cls(cls.STAGE, str(stage))

    @classmethod
    def at_run_end(cls) -> "CompletionPoint":
        return cls(cls.RUN_END)

    def reached(self, stage: str, ended: bool) -> bool:
        """A run that ended finished its work whatever the stage says; otherwise only the named stage counts."""
        return ended or (self.kind == self.STAGE and str(stage) == self.stage)

    def to_payload(self) -> dict:
        return {"kind": self.kind, "stage": self.stage}

    @classmethod
    def from_payload(cls, data: dict) -> "CompletionPoint":
        return cls(data["kind"], data.get("stage", ""))


class CompletionPoints:
    """The completion point of each action."""

    TABLE: ClassVar[dict[MeteredAction, CompletionPoint]] = {
        MeteredAction.LESSON_CREATE: CompletionPoint.at_stage(Stage.AWAITING_DIAGNOSTIC),
        MeteredAction.LESSON_CONTINUE: CompletionPoint.at_stage(Stage.READY),
        MeteredAction.LESSON_FOLLOWUP: CompletionPoint.at_stage(
            Stage.READY
        ),  # a follow-up has no quiz stage to finish at
        MeteredAction.SHEET_GENERATE: CompletionPoint.at_run_end(),
        # the `question_bank` run ends exactly when the attempt starts (its last step moves it to in_progress)
        MeteredAction.TEST_RETAKE: CompletionPoint.at_run_end(),
        # a quiz's run ends exactly when its attempt starts; the calibration walk pauses the run, which is no end
        MeteredAction.QUIZ_CREATE: CompletionPoint.at_run_end(),
        MeteredAction.QUIZ_RETAKE: CompletionPoint.at_run_end(),
    }

    #: a lesson found by self-rating has no quiz stage to finish at: the one `lesson.create` covers the whole lesson
    WHOLE_LESSON: ClassVar[CompletionPoint] = CompletionPoint.at_stage(Stage.READY)

    @classmethod
    def of(cls, action: MeteredAction, size: dict | None = None) -> CompletionPoint:
        """Where the action is complete. `size` matters for `lesson.create`, whose `covers` hint says whether it covers
        only the quiz stage or the whole lesson."""
        if MeteredAction(action) is MeteredAction.LESSON_CREATE and (size or {}).get("covers") == "all":
            return cls.WHOLE_LESSON
        return cls.TABLE[MeteredAction(action)]


@dataclass(frozen=True)
class ActionContext:
    """What the gate is asked: who, what, how big, about which row, and the point at which the work is done."""

    user: Any
    action: MeteredAction
    size: dict  # non-secret hints such as `choice`, `perfect`, `origin`, `grounding`, `sheets`
    subject_id: Any  # generated before the ask, so the new row can use it as its id
    key: str  # the action and subject, plus the resume number or the client's Idempotency-Key
    resume: bool  # true for a Retry
    completes_at: CompletionPoint


@dataclass(frozen=True)
class Authorization:
    """The gate's yes. Stored on the run it authorizes (`GraphRun.payload["authorization"]`), so nothing new is needed
    in the schema. `tracked` is false for the open gate, whose yes is not worth storing."""

    id: str
    action: MeteredAction
    size: dict
    resume: bool
    completes_at: CompletionPoint
    meta: dict = field(default_factory=dict)  # free for the gate
    tracked: bool = True

    @classmethod
    def of(cls, context: ActionContext, *, meta: dict | None = None, tracked: bool = True) -> "Authorization":
        """What a gate returns for a context it accepts."""
        return cls(
            id=str(uuid.uuid4()),
            action=context.action,
            size=dict(context.size),
            resume=context.resume,
            completes_at=context.completes_at,
            meta=dict(meta or {}),
            tracked=tracked,
        )

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "action": str(self.action),
            "size": self.size,
            "resume": self.resume,
            "completes_at": self.completes_at.to_payload(),
            "meta": self.meta,
        }

    @classmethod
    def from_payload(cls, data: dict) -> "Authorization":
        return cls(
            id=data["id"],
            action=MeteredAction(data["action"]),
            size=data["size"],
            resume=data["resume"],
            completes_at=CompletionPoint.from_payload(data["completes_at"]),
            meta=data.get("meta", {}),
        )


class ActionRefused(LessonError):
    """The one refusal. Its status is a placeholder: it is decided when the feature behind the gate is designed."""

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "action_refused"
    default_detail = "That is not available right now."


class ActionGate(Protocol):
    def authorize(self, context: ActionContext) -> Authorization:
        """Say yes with an `Authorization`, or raise `ActionRefused`."""
        ...

    def settle(self, authorization: Authorization, outcome: RunOutcome) -> None:
        """Be told how the authorized work ended. Called once per authorization."""
        ...


class OpenGate:
    """The default: everything is allowed and nothing is recorded."""

    def authorize(self, context: ActionContext) -> Authorization:
        return Authorization.of(context, tracked=False)

    def settle(self, authorization: Authorization, outcome: RunOutcome) -> None:
        pass


class ActionGates:
    @staticmethod
    def default() -> ActionGate:
        """The gate named by the `ACTION_GATE` setting, as `LESSON_TASK_QUEUE` names the queue."""
        return import_string(settings.ACTION_GATE)()


@dataclass(frozen=True)
class StoredAuthorization:
    authorization: Authorization
    settled: RunOutcome | None
    run_id: Any


class AuthorizationLedger:
    """Reads and writes authorizations on runs. A settled one is marked, so each is reported to the gate once."""

    KEY = "authorization"

    def payload(self, authorization: Authorization) -> dict:
        return {self.KEY: authorization.to_payload()} if authorization.tracked else {}

    def read(self, run: GraphRun) -> StoredAuthorization | None:
        stored = (run.payload or {}).get(self.KEY)
        if not stored:
            return None
        settled = RunOutcome(stored["settled"]) if stored.get("settled") else None
        return StoredAuthorization(Authorization.from_payload(stored), settled, run.pk)

    def latest(self, subject: RunSubject) -> GraphRun | None:
        """The newest run of the subject that holds an authorization."""
        runs = GraphRun.objects.for_subject(subject).filter(payload__has_key=self.KEY)
        return runs.order_by("-created_at").first()

    def count(self, subject_id) -> int:
        return GraphRun.objects.for_subject_id(subject_id).filter(payload__has_key=self.KEY).count()

    def settle_once(self, run_id, outcome: RunOutcome, settle: Callable[[Authorization, RunOutcome], None]) -> bool:
        """Report to the gate and mark the run, under a row lock, unless it was settled already. False if it was.
        If the gate raises, nothing is marked, so a later attempt can settle it."""
        with transaction.atomic():
            run = GraphRun.objects.select_for_update().get(pk=run_id)
            stored = self.read(run)
            if stored is None or stored.settled is not None:
                return False
            settle(stored.authorization, outcome)
            marked = {**run.payload[self.KEY], "settled": outcome.value}
            GraphRun.objects.filter(pk=run_id).update(payload={**run.payload, self.KEY: marked})
        return True


class ActionMetering:
    """What the services use: ask the gate, keep the answer on the run, carry it, ask again, release it."""

    def __init__(self, gate: ActionGate | None = None, ledger: AuthorizationLedger | None = None):
        self._gate = gate
        self.ledger = ledger or AuthorizationLedger()

    @property
    def gate(self) -> ActionGate:
        if self._gate is None:
            self._gate = ActionGates.default()
        return self._gate

    def authorize(
        self, user, action: MeteredAction, *, size: dict, subject_id, client_key: str = "", resume: bool = False
    ) -> Authorization:
        """Ask before anything exists. Raises `ActionRefused` when the gate says no."""
        key = f"{action}:{subject_id}"
        if resume:
            key += f":resume{self.ledger.count(subject_id)}"
        if client_key:
            key += f":{client_key}"
        point = CompletionPoints.of(action, size)
        context = ActionContext(user, action, dict(size), subject_id, key, resume, point)
        return self.gate.authorize(context)

    def payload(self, authorization: Authorization | None) -> dict:
        """What to put in the run's payload for this authorization."""
        return self.ledger.payload(authorization) if authorization else {}

    def carry(self, subject: RunSubject) -> dict:
        """The subject's open authorization, for a run that carries on the same action (the prerequisite quiz after a
        diagnostic): the work is not done yet, so it is not asked again. Nothing once it is settled."""
        latest = self.ledger.latest(subject)
        stored = self.ledger.read(latest) if latest else None
        if stored is None or stored.settled is not None:
            return {}
        return {AuthorizationLedger.KEY: dict(latest.payload[AuthorizationLedger.KEY])}

    def ask_again(self, lesson) -> Authorization | None:
        """For a Retry: the last flow run's authorization was released (Stop or failure), so the same action is asked
        again as a resume. Nothing is asked when that run held none, or its work was kept."""
        last = GraphRun.objects.for_subject(lesson).filter(graph=GraphRun.Graph.FLOW).order_by("-created_at").first()
        stored = self.ledger.read(last) if last else None
        if stored is None or stored.settled is RunOutcome.SUCCEEDED:
            return None
        if stored.settled is None:  # a hold nobody released: let it go before taking a new one
            self.ledger.settle_once(last.pk, RunOutcome.FAILED, self.gate.settle)
        asked = stored.authorization
        return self.authorize(lesson.owner, asked.action, size=asked.size, subject_id=lesson.id, resume=True)

    def settle_open(self, subject: RunSubject, outcome: RunOutcome) -> None:
        """Release whatever is still open on the subject, which is being deleted. A failing gate must not block that."""
        latest = self.ledger.latest(subject)
        if latest is None:
            return
        try:
            self.ledger.settle_once(latest.pk, outcome, self.gate.settle)
        except Exception:
            logger.exception("The action gate could not settle run %s as %s", latest.pk, outcome)

    @contextmanager
    def guard(self, authorization: Authorization | None) -> Iterator[None]:
        """Release the authorization as failed if the rows it was for could not be created."""
        try:
            yield
        except Exception:
            if authorization is not None:
                try:
                    self.gate.settle(authorization, RunOutcome.FAILED)
                except Exception:
                    logger.exception("The action gate could not release authorization %s", authorization.id)
            raise


class AuthorizationSettlement:
    """Tells the gate how a run's work ended: `succeeded` when the completion point is reached, otherwise `failed` or
    `cancelled` when the run dies first. Called by `RunEffects` next to the per-graph effects."""

    def __init__(self, gate: ActionGate | None = None, ledger: AuthorizationLedger | None = None):
        self._gate = gate
        self.ledger = ledger or AuthorizationLedger()

    @property
    def gate(self) -> ActionGate:
        if self._gate is None:
            self._gate = ActionGates.default()
        return self._gate

    def on_finished(self, run: GraphRun, *, ended: bool = False) -> None:
        """The run paused (`ended` false) or ran to its end (true)."""
        stored = self.ledger.read(run)
        if stored is None or stored.settled is not None:
            return
        if stored.authorization.completes_at.reached(run.fresh_subject().stage, ended):
            self._settle(run, RunOutcome.SUCCEEDED)

    def on_stopped(self, run: GraphRun, message: str) -> None:
        """The run died: Stop settles `cancelled`, anything else `failed`. The status is read from the database,
        because a Stop updates it behind the caller's copy and the runner marks a failure only after this."""
        stored = self.ledger.read(run)
        if stored is None or stored.settled is not None:
            return
        cancelled = GraphRun.objects.filter(pk=run.pk, status=GraphRun.Status.CANCELLED).exists()
        self._settle(run, RunOutcome.CANCELLED if cancelled else RunOutcome.FAILED)

    def _settle(self, run: GraphRun, outcome: RunOutcome) -> None:
        try:
            self.ledger.settle_once(run.pk, outcome, self.gate.settle)
        except Exception:
            logger.exception("The action gate could not settle run %s as %s", run.pk, outcome)


class RunStarters:
    """Every service method that queues a run, and how metering treats it. A test fails when one is missing, so no
    costly entry point ships unclassified."""

    METERED: ClassVar[dict[str, MeteredAction]] = {
        "LessonService.create": MeteredAction.LESSON_CREATE,
        "QuizService.submit": MeteredAction.LESSON_CONTINUE,
        "MaterialService.choose": MeteredAction.LESSON_CONTINUE,
        "MaterialService.request_extra": MeteredAction.SHEET_GENERATE,
        "AttemptService.start": MeteredAction.TEST_RETAKE,  # attempt 2 onward; attempt 1 is part of the lesson
        "FollowupService.create": MeteredAction.LESSON_FOLLOWUP,
        "QuickQuizService.create": MeteredAction.QUIZ_CREATE,
        "QuickQuizService.retake": MeteredAction.QUIZ_RETAKE,
    }
    #: asks again for the action of the run it resumes
    RESUMING: ClassVar[tuple[str, ...]] = ("LessonService.retry",)
    NEVER: ClassVar[dict[str, str]] = {
        "CodeService.request_repair": "A repair of a lesson that is already paid for; capped per lesson.",
        "AttemptService.submit": "Grading the learner's test; a lesson attempt is graded in full here, no run.",
        "AttemptService.regrade": "Re-running a grading that failed, on the stored answers.",
        "CalibrationService.answer": "The calibration walk resumes the run that is already paid for (quiz.create).",
        "QuizAttemptService.submit": "Grading the learner's quiz attempt; objective attempts are graded in full here.",
        "QuizAttemptService.regrade": "Re-running a grading that failed, on the stored answers.",
    }

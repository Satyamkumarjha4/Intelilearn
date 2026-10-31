"""The use cases behind the lessons API. Views parse and format; these decide.

`LessonService` starts, retries and deletes lessons. `QuizService` serves a quiz to the learner, grades their answers
(with the same grader the graph uses, so the score they see is the one the graph routes on) and queues the resume.
The lesson test's attempts are in `attempts.py`.
"""

import uuid
from typing import Protocol

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from graph.followups import FollowupTargets
from graph.grading import AnswerError, AnswerGrader, QuizGrader, RoutingPolicy, Solution
from graph.levels import Level, StarRating
from graph.schemas import public_question
from llm_registry.resolver import RegistryResolver

from .document import LessonDocumentBuilder
from .effects import RunEffects
from .erasure import LessonErasure
from .errors import (
    AlreadyAttempted,
    AlreadyExists,
    InvalidAnswers,
    LessonNotConfigured,
    MaterialNotFound,
    NotAttempted,
    QueueUnavailable,
    QuizNotFound,
    RepairLimitReached,
    RunEnded,
    RunInProgress,
    StaleCodeVersion,
    VersionNotFound,
    WrongStage,
)
from .events import EventPublisher, RedisEventPublisher, RunEvent
from .metering import ActionGate, ActionMetering, AuthorizationSettlement, MeteredAction, RunOutcome
from .models import (
    Entry,
    FlowSettings,
    GraphRun,
    Intent,
    Lesson,
    LessonVersion,
    MaterialKind,
    Origin,
    Quiz,
    QuizAttempt,
    Route,
    Stage,
    StudyMaterial,
)
from .origins import OriginVerifier
from .sheet_requests import SheetGroundingHint, SheetRequest
from .stop_point import StopPoint
from .subjects import RunSubject


class TaskQueue(Protocol):
    def enqueue(self, run: GraphRun) -> None: ...


class RunDispatcher:
    """Queues a run. If the queue is unreachable the run is failed (and so the lesson), so Retry works later."""

    def __init__(self, queue: TaskQueue | None = None, effects: RunEffects | None = None):
        self.queue = queue or import_string(settings.LESSON_TASK_QUEUE)()
        self.effects = effects or RunEffects()

    def dispatch(self, run: GraphRun) -> None:
        try:
            self.queue.enqueue(run)
        except QueueUnavailable as exc:
            GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.FAILED, error=str(exc.detail))
            run.subject.fail(str(exc.detail))
            self.effects.on_stopped(run, str(exc.detail))
            raise


def has_active_run(subject: RunSubject) -> bool:
    return (
        GraphRun.objects.for_subject(subject)
        .filter(status__in=[GraphRun.Status.QUEUED, GraphRun.Status.RUNNING])
        .exists()
    )


class LessonService:
    #: the steps that must have a model before a lesson can start, by how its level is found
    FIRST_NODES = {
        Entry.DIAGNOSTIC: ("diagnostic.generate",),
        Entry.SELF_RATING: ("lesson.plan",),
        Entry.FOLLOWUP: ("lesson.plan",),
    }
    #: what is also needed by a Beginner who took no quick check: nobody tested them, so their prerequisites are planned
    BEGINNER_NODES = ("prerequisites.plan",)
    #: a lesson that is only sheets needs the sheet writer, and no lesson planner (nor prerequisites to plan)
    SHEETS_NODES = ("study.generate",)

    def __init__(
        self,
        queue: TaskQueue | None = None,
        resolver: RegistryResolver | None = None,
        events: EventPublisher | None = None,
        erasure: LessonErasure | None = None,
        gate: ActionGate | None = None,
        origins: OriginVerifier | None = None,
    ):
        self.metering = ActionMetering(gate)
        self.effects = RunEffects(settlement=AuthorizationSettlement(gate))
        self.dispatcher = RunDispatcher(queue, self.effects)
        self.origins = origins or OriginVerifier()
        self.resolver = resolver or RegistryResolver()
        self.events = events or RedisEventPublisher()
        self.stops = StopPoint()
        self.erasure = erasure or LessonErasure()

    def create(
        self,
        user,
        topic: str,
        user_context: str = "",
        idempotency_key: str = "",
        *,
        entry: str = Entry.DIAGNOSTIC,
        self_rating_halves: int | None = None,
        intent: str = Intent.LESSON,
        origin: str = Origin.DIRECT,
        recommended_from: dict | None = None,
        sheets: list[str] | None = None,
    ) -> tuple[Lesson, GraphRun]:
        """A new lesson with its registry and settings snapshotted, and a queued start run. The origin is verified and
        the action gate is asked first (`lesson.create`), so a refusal creates nothing. A quick check starts with the
        quiz; a self-rated lesson has none and goes straight to the plan (`covers: all`). A lesson that asks for
        `sheets` (intent sheets) is written as those sheets and has no pages and no test."""
        if entry == Entry.SELF_RATING and self_rating_halves is None:
            raise ValueError("A self-rated lesson needs the learner's rating.")
        kinds = SheetRequest.kinds(sheets) if intent == Intent.SHEETS else self.no_sheets(sheets)
        verified = self.origins.verify(user, origin, recommended_from)
        snapshot = self.resolver.snapshot()
        self.require_models(snapshot, entry, self_rating_halves, intent=intent)
        lesson_id = uuid.uuid4()
        authorization = self.metering.authorize(
            user,
            MeteredAction.LESSON_CREATE,
            size=self.size_of(entry, intent, verified.origin, len(kinds)),
            subject_id=lesson_id,
            client_key=idempotency_key,
        )
        with self.metering.guard(authorization), transaction.atomic():
            lesson = Lesson.objects.create(
                id=lesson_id,
                owner=user,
                topic=topic.strip(),
                user_context=user_context.strip(),
                entry=entry,
                intent=intent,
                origin=verified.origin,
                recommended_from=verified.recommended_from,
                self_rating_halves=self_rating_halves if entry == Entry.SELF_RATING else None,
                config_snapshot=snapshot.to_json(),
                settings_snapshot=FlowSettings.load().snapshot(),
            )
            run = GraphRun.objects.create(
                lesson=lesson,
                graph=GraphRun.Graph.FLOW,
                trigger=GraphRun.Trigger.START,
                payload={
                    **self.metering.payload(authorization),
                    **({"input": {"sheet_kinds": kinds}} if kinds else {}),
                },
            )
        self.dispatcher.dispatch(run)
        return lesson, run

    @staticmethod
    def no_sheets(sheets: list[str] | None) -> list[str]:
        """A lesson takes no list of sheets: that is asked for with the intent."""
        if sheets:
            raise ValueError("Only a lesson that asks for sheets takes a list of sheets.")
        return []

    @staticmethod
    def size_of(entry: str, intent: str, origin: str, sheets: int = 0) -> dict:
        """What `lesson.create` is asked with. A quick check asks for the quiz stage only; a self-rated lesson has no
        quiz, so it covers everything. A lesson that asks for sheets also says how many, and what they rest on."""
        size = {
            "entry": str(entry), "intent": str(intent), "origin": str(origin),
            "covers": "all" if entry == Entry.SELF_RATING else "diagnostic",
        }  # fmt: skip
        if intent == Intent.SHEETS:
            size |= {"sheets": sheets, "grounding": "quiz" if entry == Entry.DIAGNOSTIC else "none"}
        return size

    def require_models(
        self,
        snapshot,
        entry: str,
        self_rating_halves: int | None = None,
        followup_level: str | None = None,
        intent: str = Intent.LESSON,
    ) -> None:
        """Every step the first stretch of this lesson needs has a model, or the lesson would fail at once."""
        needed = list(self.FIRST_NODES[Entry(entry)])
        if intent == Intent.SHEETS:
            needed = [key for key in needed if key != "lesson.plan"] + list(self.SHEETS_NODES)
        level = {
            Entry.SELF_RATING: lambda: StarRating(self_rating_halves).level(),
            Entry.FOLLOWUP: lambda: FollowupTargets.level_for(followup_level),
        }.get(Entry(entry))
        if intent != Intent.SHEETS and level and level() is Level.BEGINNER:
            needed += self.BEGINNER_NODES
        for key in needed:
            node = snapshot.node(key)
            if not node.enabled or not node.chain:
                raise LessonNotConfigured(
                    f"No AI model is bound to '{key}'. An admin must bind one in the model registry first."
                )

    def retry(self, lesson: Lesson) -> GraphRun:
        """Resume a failed lesson from its last checkpoint. After a Stop, the lesson first goes back to the stage it was
        stopped in, and the retry carries the answer the stopped run was about to give."""
        if lesson.stage != Stage.FAILED:
            raise WrongStage("Only a failed lesson can be retried.")
        if has_active_run(lesson):
            raise RunInProgress()
        stage, payload = self.stops.of(lesson)
        authorization = self.metering.ask_again(lesson)  # Stop and failure released the last one; a refusal ends here
        with self.metering.guard(authorization), transaction.atomic():
            if stage is not None:
                lesson.advance_to(stage)
            run = GraphRun.objects.create(
                lesson=lesson,
                graph=GraphRun.Graph.FLOW,
                trigger=GraphRun.Trigger.RETRY,
                payload={**payload, **self.metering.payload(authorization)},
            )
        self.dispatcher.dispatch(run)
        return run

    def cancel(self, run: GraphRun) -> None:
        """Stop an active run after its current step. The lesson is marked failed, which makes it retryable, and the run
        remembers where the lesson was (`StopPoint`), because Retry has to pick up from there."""
        stopped = GraphRun.objects.filter(pk=run.pk, status__in=[GraphRun.Status.QUEUED, GraphRun.Status.RUNNING])
        if not stopped.update(status=GraphRun.Status.CANCELLED, finished_at=timezone.now()):
            raise RunEnded()
        self.stops.remember(run)
        run.subject.fail("Cancelled. Press Retry to continue where it stopped.")
        self.effects.on_stopped(run, "Cancelled before it finished.")
        self.events.publish(run.id, RunEvent("cancelled", {}))

    def delete(self, lesson: Lesson) -> list:
        """Cancel whatever is running, erase what the cascade does not reach (LangGraph checkpoints, model calls), then
        remove the lesson and everything attached (media files go with them). Erasing comes first, so if it fails the
        lesson is still there and the delete can be repeated."""
        active = GraphRun.objects.for_subject(lesson).filter(
            status__in=[GraphRun.Status.QUEUED, GraphRun.Status.RUNNING]
        )
        cancelled = list(active.values_list("pk", flat=True))
        active.update(status=GraphRun.Status.CANCELLED)
        self.metering.settle_open(lesson, RunOutcome.CANCELLED)
        self.erasure.erase(lesson)
        lesson.delete()
        return cancelled


class QuizService:
    #: kind → the stage the lesson waits in for that quiz, and the trigger of the run that resumes it
    KINDS = {
        Quiz.Kind.DIAGNOSTIC: (Stage.AWAITING_DIAGNOSTIC, GraphRun.Trigger.RESUME_DIAGNOSTIC),
        Quiz.Kind.PREREQUISITE: (Stage.AWAITING_PREREQUISITE, GraphRun.Trigger.RESUME_PREREQUISITE),
    }

    def __init__(
        self,
        queue: TaskQueue | None = None,
        grader: QuizGrader | None = None,
        policy: RoutingPolicy | None = None,
        gate: ActionGate | None = None,
    ):
        self.metering = ActionMetering(gate)
        self.dispatcher = RunDispatcher(queue, RunEffects(settlement=AuthorizationSettlement(gate)))
        self.grader = grader or QuizGrader()
        self.policy = policy or RoutingPolicy()

    def for_learner(self, lesson: Lesson, kind: str) -> dict:
        quiz = self._quiz(lesson, kind)
        return {
            "quiz_id": str(quiz.id),
            "kind": quiz.kind,
            "questions": quiz.public_questions(),
            "allow_dont_know": True,
        }

    def submit(self, lesson: Lesson, kind: str, answers) -> tuple[dict, GraphRun]:
        stage, trigger = self._kind(kind)
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
            quiz = self._quiz(lesson, kind)
            if QuizAttempt.objects.filter(quiz=quiz).exists():
                raise AlreadyAttempted()  # before the stage: once the lesson has moved on, this is still the answer
            if lesson.stage != stage:
                raise WrongStage(f"The lesson is not waiting for the {kind} quiz.")
            if has_active_run(lesson):
                raise RunInProgress()
            if not isinstance(answers, dict):
                raise InvalidAnswers("Send the answers as an object of question id → option index.")
            try:
                result = self.grader.grade(quiz.questions, answers)
            except AnswerError as exc:
                raise InvalidAnswers(str(exc)) from exc
            route = self.policy.route_for(result, lesson.settings_snapshot) if kind == Quiz.Kind.DIAGNOSTIC else None
            authorization = self.authorization_for(lesson, kind, route)  # after grading, before anything is stored
            with self.metering.guard(authorization):
                attempt = QuizAttempt.objects.create(quiz=quiz, answers=answers, result=result.as_dict())
                run = GraphRun.objects.create(
                    lesson=lesson,
                    graph=GraphRun.Graph.FLOW,
                    trigger=trigger,
                    payload={"resume": str(attempt.id), **self.metering_payload(lesson, kind, authorization)},
                )
        self.dispatcher.dispatch(run)
        # A lesson that asked for sheets is neither a lesson nor a mastery lesson, so it is shown no route.
        return result.summary(None if lesson.intent == Intent.SHEETS else route), run

    def authorization_for(self, lesson: Lesson, kind: str, route: str | None):
        """`lesson.continue` is asked when a diagnostic leads to a lesson (not a perfect score: that learner chooses
        first, and `MaterialService.choose` asks). A lesson that asked for sheets is asked at once, whatever the score:
        the choice was made when it was asked for. The prerequisite quiz asks nothing; it carries on the open one."""
        if kind != Quiz.Kind.DIAGNOSTIC:
            return None
        if lesson.intent == Intent.SHEETS:
            return self.metering.authorize(
                lesson.owner,
                MeteredAction.LESSON_CONTINUE,
                size={
                    "choice": "sheets_only",
                    "perfect": route == Route.MASTERY,
                    "intent": "sheets",
                    "sheets": len(SheetRequest.of(lesson)),
                    "grounding": "quiz",
                },  # fmt: skip
                subject_id=lesson.id,
            )
        if route == Route.MASTERY:
            return None
        return self.metering.authorize(
            lesson.owner,
            MeteredAction.LESSON_CONTINUE,
            size={"choice": "lesson", "perfect": False},
            subject_id=lesson.id,
        )

    def metering_payload(self, lesson: Lesson, kind: str, authorization) -> dict:
        if kind == Quiz.Kind.PREREQUISITE:
            return self.metering.carry(lesson)
        return self.metering.payload(authorization)

    def review(self, lesson: Lesson, kind: str) -> dict:
        quiz = self._quiz(lesson, kind)
        attempt = QuizAttempt.objects.filter(quiz=quiz).first()
        if attempt is None:
            raise NotAttempted()
        questions = [
            {
                **{
                    key: q[key]
                    for key in ("id", "band", "question", "options", "correct_index", "explanation")
                    if key in q
                },
                "answer": attempt.answers[q["id"]],
                "correct": attempt.result["per_question"][q["id"]],
            }
            for q in quiz.questions
        ]
        return {
            "quiz_id": str(quiz.id),
            "kind": quiz.kind,
            "questions": questions,
            "result": attempt.result,
            "submitted_at": attempt.submitted_at,
        }

    def _kind(self, kind: str):
        try:
            return self.KINDS[Quiz.Kind(kind)]
        except ValueError:
            raise QuizNotFound() from None

    def _quiz(self, lesson: Lesson, kind: str) -> Quiz:
        self._kind(kind)
        quiz = Quiz.objects.filter(lesson=lesson, kind=kind).first()
        if quiz is None:
            raise QuizNotFound()
        return quiz


class MaterialService:
    """Study sheets: choosing the first one (resumes the flow), asking for more, serving them, grading practice."""

    def __init__(
        self, queue: TaskQueue | None = None, grader: AnswerGrader | None = None, gate: ActionGate | None = None
    ):
        self.metering = ActionMetering(gate)
        self.dispatcher = RunDispatcher(queue, RunEffects(settlement=AuthorizationSettlement(gate)))
        self.grader = grader or AnswerGrader()

    #: what a learner who aced the quiz can choose now (a sheet kind is still taken from a lesson already waiting)
    CHOICES = ("lesson", "sheets")

    def choose(self, lesson: Lesson, choice: str) -> GraphRun:
        """The learner's pick after aceing the diagnostic: resume the paused flow with it. `lesson` continues with an
        Expert lesson that has a test; `sheets` writes the cheat sheet and the revision sheet and ends there (no test).
        `lesson.continue` is asked with what they chose."""
        if choice not in (*self.CHOICES, *MaterialKind.values):
            raise InvalidAnswers(f"Unknown choice {choice!r}.")
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
            if lesson.stage != Stage.AWAITING_CHOICE:
                raise WrongStage("The lesson is not waiting for a study sheet choice.")
            if has_active_run(lesson):
                raise RunInProgress()
            authorization = self.metering.authorize(
                lesson.owner,
                MeteredAction.LESSON_CONTINUE,
                size=self.size_of(choice),
                subject_id=lesson.id,
            )
            with self.metering.guard(authorization):
                run = GraphRun.objects.create(
                    lesson=lesson,
                    graph=GraphRun.Graph.FLOW,
                    trigger=GraphRun.Trigger.RESUME_CHOICE,
                    payload={"resume": {"choice": choice}, **self.metering.payload(authorization)},
                )
        self.dispatcher.dispatch(run)
        return run

    @staticmethod
    def size_of(choice: str) -> dict:
        """What `lesson.continue` is asked with after a perfect score: the Expert lesson, or sheets only."""
        if choice == "lesson":
            return {"choice": "lesson", "perfect": True}
        return {"choice": "sheets_only", "perfect": True, "sheets": 2 if choice == "sheets" else 1, "grounding": "quiz"}

    def request_extra(self, lesson: Lesson, asked: str | list[str], idempotency_key: str = "") -> GraphRun:
        """More sheets for a ready lesson, whichever kind of lesson it is: one cheat sheet, one revision sheet, or both
        at once, written by the small `study_material` graph. If any of them exists nothing is made or asked, and the
        error names the ones that do (a sheet is never made twice, and has no versions). One request is one run and
        one `sheet.generate`."""
        kinds = SheetRequest.kinds(asked)
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
            if lesson.stage != Stage.READY:
                raise WrongStage("Study sheets can be added once the lesson is ready.")
            if existing := [k for k in kinds if StudyMaterial.objects.filter(lesson=lesson, kind=k).exists()]:
                raise AlreadyExists(existing)
            if has_active_run(lesson):
                raise RunInProgress()
            authorization = self.metering.authorize(
                lesson.owner,
                MeteredAction.SHEET_GENERATE,
                size={"sheets": len(kinds), "grounding": SheetGroundingHint.of(lesson)},
                subject_id=lesson.id,
                client_key=idempotency_key,
            )
            with self.metering.guard(authorization):
                run = GraphRun.objects.create(
                    lesson=lesson,
                    graph=GraphRun.Graph.STUDY_MATERIAL,
                    trigger=GraphRun.Trigger.EXTRA_MATERIAL,
                    payload={
                        "input": {"sheet_kinds": kinds, "extra_material": True},
                        **self.metering.payload(authorization),
                    },
                )
        self.dispatcher.dispatch(run)
        return run

    def listing(self, lesson: Lesson) -> list[dict]:
        """The sheets the lesson has, oldest first, so the tab row knows which exist."""
        return list(lesson.materials.order_by("created_at").values("kind", "created_at"))

    def kinds(self, lesson: Lesson) -> list[str]:
        return sorted(lesson.materials.values_list("kind", flat=True))

    def get(self, lesson: Lesson, kind: str, reveal: list[str] | None = None) -> dict:
        """The sheet. A practice sheet's questions come without solutions; `reveal` (ids, or "all") adds some."""
        material = self._material(lesson, kind)
        content = material.content
        if kind != MaterialKind.PRACTICE_SHEET:
            return {"kind": kind, "content": content, "solutions": {}}
        wanted = {q["id"] for q in content["questions"]} if "all" in (reveal or []) else set(reveal or [])
        solutions = {q["id"]: Solution.of(q) for q in content["questions"] if q["id"] in wanted}
        public = {**content, "questions": [public_question(q) | {"id": q["id"]} for q in content["questions"]]}
        return {"kind": kind, "content": public, "solutions": solutions}

    def grade_practice(self, lesson: Lesson, answers) -> dict:
        """Mark a practice sheet on submit. What cannot be marked here shows its solution for self-checking."""
        material = self._material(lesson, MaterialKind.PRACTICE_SHEET)
        if not isinstance(answers, dict):
            raise InvalidAnswers("Send the answers as an object of question id → answer.")
        questions = material.content["questions"]
        sheet = self.grader.grade_all(questions, answers)
        by_id = {q["id"]: q for q in questions}
        results = [
            {
                "id": g.question_id,
                "correct": g.correct,
                "marks": g.marks,
                "awarded": g.awarded,
                "solution": Solution.of(by_id[g.question_id]),
            }
            for g in sheet.grades
        ]
        score = {
            "awarded": sheet.awarded, "available": sheet.available, "open_marks": sheet.open_marks,
            "correct": sheet.correct, "marked": sheet.marked,
        }  # fmt: skip
        return {"score": score, "results": results}

    @staticmethod
    def _material(lesson: Lesson, kind: str) -> StudyMaterial:
        if kind not in MaterialKind.values:
            raise MaterialNotFound()
        material = StudyMaterial.objects.filter(lesson=lesson, kind=kind).first()
        if material is None:
            raise MaterialNotFound()
        return material


class CodeService:
    """The code of a ready lesson: serving the document, repairing it after a crash, and going back to a version."""

    #: used when a lesson's settings snapshot predates the setting
    DEFAULT_REPAIR_LIMIT = 2

    def __init__(self, queue: TaskQueue | None = None, documents: LessonDocumentBuilder | None = None):
        self.dispatcher = RunDispatcher(queue)
        self.documents = documents or LessonDocumentBuilder()

    def document(self, lesson: Lesson) -> dict:
        if lesson.stage != Stage.READY or not lesson.code:
            raise WrongStage("The lesson document is available once the lesson is ready.")
        return self.documents.build(lesson)

    def request_repair(self, lesson: Lesson, error: dict, code_version: int) -> GraphRun:
        """Queue a `runtime_repair` for a crash the browser reported. Each request counts against the lesson's cap
        (`max_auto_runtime_repairs`) whether or not the repair succeeds, so a crash the model cannot fix cannot loop."""
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
            if lesson.stage != Stage.READY or not lesson.code:
                raise WrongStage("Only a ready lesson can be repaired.")
            if code_version != lesson.code_version:
                raise StaleCodeVersion()
            limit = lesson.settings_snapshot.get("max_auto_runtime_repairs", self.DEFAULT_REPAIR_LIMIT)
            if lesson.runtime_repairs >= limit:
                raise RepairLimitReached()
            if has_active_run(lesson):
                raise RunInProgress()
            Lesson.objects.filter(pk=lesson.pk).update(runtime_repairs=lesson.runtime_repairs + 1)
            run = GraphRun.objects.create(
                lesson=lesson,
                graph=GraphRun.Graph.RUNTIME_REPAIR,
                trigger=GraphRun.Trigger.REPAIR,
                payload={"input": {"repair_error": error, "expected_code_version": code_version}},
            )
        self.dispatcher.dispatch(run)
        return run

    def versions(self, lesson: Lesson):
        return lesson.versions.all()

    def restore(self, lesson: Lesson, number: int) -> Lesson:
        """Make an earlier version current again. The code being replaced is kept as a version, and the restored code
        gets a new `code_version`, so a browser still showing the old one is told it is stale."""
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
            if lesson.stage != Stage.READY:
                raise WrongStage("Only a ready lesson can go back to an earlier version.")
            version = LessonVersion.objects.filter(lesson=lesson, code_version=number).first()
            if version is None:
                raise VersionNotFound()
            if has_active_run(lesson):
                raise RunInProgress()
            LessonVersion.objects.create(
                lesson=lesson,
                code_version=lesson.code_version,
                code=lesson.code,
                code_parts=lesson.code_parts,
                reason=f"Before going back to version {number}",
            )
            lesson.code, lesson.code_parts = version.code, version.code_parts
            lesson.code_version += 1
            lesson.save(update_fields=["code", "code_parts", "code_version", "updated_at"])
        return lesson

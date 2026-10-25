"""The use cases behind the lessons API. Views parse and format; these decide.

`LessonService` starts, retries and deletes lessons. `QuizService` serves a quiz to the learner, grades their answers
(with the same grader the graph uses, so the score they see is the one the graph routes on) and queues the resume.
"""

from typing import Protocol

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from graph.grading import AnswerError, AnswerGrader, QuizGrader, RoutingPolicy, ScoreCard, Solution
from graph.schemas import public_question
from llm_registry.resolver import RegistryResolver

from .document import LessonDocumentBuilder
from .effects import RunEffects
from .errors import (
    AlreadyAttempted,
    AlreadyExists,
    AlreadySubmitted,
    InvalidAnswers,
    LessonNotConfigured,
    MaterialNotFound,
    NotAttempted,
    NotFailed,
    QueueUnavailable,
    QuizNotFound,
    RepairLimitReached,
    RunEnded,
    RunInProgress,
    StaleCodeVersion,
    SubmissionNotFound,
    VersionNotFound,
    WrongStage,
)
from .events import EventPublisher, RedisEventPublisher, RunEvent
from .models import (
    FlowSettings,
    GraphRun,
    Lesson,
    LessonVersion,
    MaterialKind,
    Quiz,
    QuizAttempt,
    Route,
    Stage,
    StudyMaterial,
    TestSubmission,
)


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
            run.lesson.fail(str(exc.detail))
            self.effects.on_stopped(run, str(exc.detail))
            raise


class StopPoint:
    """Where a stopped flow run left the lesson, so Retry can carry on from there.

    Stop marks the lesson failed: once a quiz is answered there is nothing the learner can do from `awaiting_*`, so the
    stopped lesson shows the Retry card. The run remembers the stage the lesson was in, and the answer it was about to
    hand the graph, and Retry puts both back.
    """

    KEY = "stopped_in"
    #: the resume trigger → the kind of pause its answer is for (an answer must never reach a different question)
    ANSWERS = {
        GraphRun.Trigger.RESUME_DIAGNOSTIC: "diagnostic",
        GraphRun.Trigger.RESUME_PREREQUISITE: "prerequisite",
        GraphRun.Trigger.RESUME_CHOICE: "mastery_choice",
    }

    def remember(self, run: GraphRun) -> None:
        """Call before the lesson is failed: the stage is read from the database, where the graph moves it."""
        if run.graph != GraphRun.Graph.FLOW:
            return
        stage = Lesson.objects.values_list("stage", flat=True).get(pk=run.lesson_id)
        if stage in (Stage.READY, Stage.FAILED):
            return
        run.payload = {**run.payload, self.KEY: stage}
        GraphRun.objects.filter(pk=run.pk).update(payload=run.payload)

    def of(self, lesson: Lesson) -> tuple[Stage | None, dict]:
        """The stage to go back to and the payload for the retry run. Nothing, unless the last flow run was stopped."""
        last = GraphRun.objects.filter(lesson=lesson, graph=GraphRun.Graph.FLOW).order_by("-created_at").first()
        if last is None or last.status != GraphRun.Status.CANCELLED or self.KEY not in last.payload:
            return None, {}
        payload = {}
        if "resume" in last.payload and last.trigger in self.ANSWERS:
            payload = {"resume": last.payload["resume"], "resume_for": self.ANSWERS[last.trigger]}
        return Stage(last.payload[self.KEY]), payload


def has_active_run(lesson: Lesson) -> bool:
    return GraphRun.objects.filter(lesson=lesson, status__in=[GraphRun.Status.QUEUED, GraphRun.Status.RUNNING]).exists()


class LessonService:
    FIRST_NODE = "diagnostic.generate"

    def __init__(
        self,
        queue: TaskQueue | None = None,
        resolver: RegistryResolver | None = None,
        events: EventPublisher | None = None,
    ):
        self.dispatcher = RunDispatcher(queue)
        self.resolver = resolver or RegistryResolver()
        self.events = events or RedisEventPublisher()
        self.stops = StopPoint()

    def create(self, user, topic: str, user_context: str = "") -> tuple[Lesson, GraphRun]:
        """A new lesson with its registry and settings snapshotted, and a queued start run."""
        snapshot = self.resolver.snapshot()
        first = snapshot.node(self.FIRST_NODE)
        if not first.enabled or not first.chain:
            raise LessonNotConfigured(
                f"No AI model is bound to '{self.FIRST_NODE}'. An admin must bind one in the model registry first."
            )
        with transaction.atomic():
            lesson = Lesson.objects.create(
                owner=user,
                topic=topic.strip(),
                user_context=user_context.strip(),
                config_snapshot=snapshot.to_json(),
                settings_snapshot=FlowSettings.load().snapshot(),
            )
            run = GraphRun.objects.create(lesson=lesson, graph=GraphRun.Graph.FLOW, trigger=GraphRun.Trigger.START)
        self.dispatcher.dispatch(run)
        return lesson, run

    def retry(self, lesson: Lesson) -> GraphRun:
        """Resume a failed lesson from its last checkpoint. After a Stop, the lesson first goes back to the stage it was
        stopped in, and the retry carries the answer the stopped run was about to give."""
        if lesson.stage != Stage.FAILED:
            raise WrongStage("Only a failed lesson can be retried.")
        if has_active_run(lesson):
            raise RunInProgress()
        stage, payload = self.stops.of(lesson)
        with transaction.atomic():
            if stage is not None:
                lesson.advance_to(stage)
            run = GraphRun.objects.create(
                lesson=lesson, graph=GraphRun.Graph.FLOW, trigger=GraphRun.Trigger.RETRY, payload=payload
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
        run.lesson.fail("Cancelled. Press Retry to continue where it stopped.")
        RunEffects().on_stopped(run, "Cancelled before it finished.")
        self.events.publish(run.id, RunEvent("cancelled", {}))

    def delete(self, lesson: Lesson) -> list:
        """Cancel whatever is running, then remove the lesson and everything attached (media files go with them)."""
        active = GraphRun.objects.filter(lesson=lesson, status__in=[GraphRun.Status.QUEUED, GraphRun.Status.RUNNING])
        cancelled = list(active.values_list("pk", flat=True))
        active.update(status=GraphRun.Status.CANCELLED)
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
    ):
        self.dispatcher = RunDispatcher(queue)
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
            attempt = QuizAttempt.objects.create(quiz=quiz, answers=answers, result=result.as_dict())
            run = GraphRun.objects.create(
                lesson=lesson, graph=GraphRun.Graph.FLOW, trigger=trigger, payload={"resume": str(attempt.id)}
            )
        route = self.policy.route_for(result, lesson.settings_snapshot) if kind == Quiz.Kind.DIAGNOSTIC else None
        self.dispatcher.dispatch(run)
        return result.summary(route), run

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

    def __init__(self, queue: TaskQueue | None = None, grader: AnswerGrader | None = None):
        self.dispatcher = RunDispatcher(queue)
        self.grader = grader or AnswerGrader()

    def choose(self, lesson: Lesson, kind: str) -> GraphRun:
        """The learner's pick after aceing the diagnostic: resume the paused flow with it."""
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
            if lesson.stage != Stage.AWAITING_CHOICE:
                raise WrongStage("The lesson is not waiting for a study sheet choice.")
            if has_active_run(lesson):
                raise RunInProgress()
            run = GraphRun.objects.create(
                lesson=lesson,
                graph=GraphRun.Graph.FLOW,
                trigger=GraphRun.Trigger.RESUME_CHOICE,
                payload={"resume": kind},
            )
        self.dispatcher.dispatch(run)
        return run

    def request_extra(self, lesson: Lesson, kind: str) -> GraphRun:
        """Another sheet for a ready mastery lesson, written by the small `study_material` graph."""
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
            if lesson.stage != Stage.READY or lesson.route != "mastery":
                raise WrongStage("More study sheets are only available once a mastery lesson is ready.")
            if StudyMaterial.objects.filter(lesson=lesson, kind=kind).exists():
                raise AlreadyExists()
            if has_active_run(lesson):
                raise RunInProgress()
            run = GraphRun.objects.create(
                lesson=lesson,
                graph=GraphRun.Graph.STUDY_MATERIAL,
                trigger=GraphRun.Trigger.EXTRA_MATERIAL,
                payload={"input": {"mastery_choice": kind, "extra_material": True}},
            )
        self.dispatcher.dispatch(run)
        return run

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


class SubmissionService:
    """The lesson's final test: serving it, marking the one submission at once, queueing the open-ended answers for
    grading, and grading again when that failed. The learner never answers twice."""

    MAX_ANSWER_CHARS = 10_000
    #: what the test screen needs of `public_question` (the stripping of answers stays there); the concept and
    #: difficulty are labels for the grader and the report, not for the person answering
    SHOWN = ("id", "type", "question", "marks", "options", "unit", "language", "starter_code")

    def __init__(
        self, queue: TaskQueue | None = None, grader: AnswerGrader | None = None, cards: ScoreCard | None = None
    ):
        self.dispatcher = RunDispatcher(queue)
        self.grader = grader or AnswerGrader()
        self.cards = cards or ScoreCard()

    def for_learner(self, lesson: Lesson) -> dict:
        """The test to take: questions without answers or marking schemes, what it is worth, and the submission if
        one was made."""
        questions = self._questions(lesson)
        submission = TestSubmission.objects.filter(lesson=lesson).first()
        return {
            "questions": [self._shown(q) for q in questions],
            "total_marks": sum(q["marks"] for q in questions),
            "submission": None
            if submission is None
            else {"id": str(submission.id), "status": submission.status, "submitted_at": submission.submitted_at},
        }

    def submit(self, lesson: Lesson, answers) -> tuple[TestSubmission, GraphRun | None]:
        """Mark what can be marked now. Open-ended answers get a `grade_test` run; with none, the result is final.
        Only the first submission is accepted: a second one stores nothing."""
        questions = self._questions(lesson)
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)  # two submits at once queue up here
            if (existing := self._existing(lesson)) is not None:
                raise AlreadySubmitted(existing.id)
            clean = self._clean(questions, answers)
            pending = bool(self.cards.open_items(questions, clean))
            sheet = self.grader.grade_all(questions, clean)
            card = self.cards.build(questions, clean, sheet, None if pending else {})
            try:
                # A savepoint: the constraint's refusal must not poison the outer transaction.
                with transaction.atomic():
                    submission = TestSubmission.objects.create(
                        lesson=lesson,
                        answers=clean,
                        result=card,
                        status=TestSubmission.Status.GRADING if pending else TestSubmission.Status.GRADED,
                        graded_at=None if pending else timezone.now(),
                    )
            except IntegrityError:  # the lock above makes this rare, but the constraint is the real guarantee
                raise AlreadySubmitted(self._existing(lesson).id) from None
            run = self._grading_run(lesson, submission) if pending else None
        if run:
            self.dispatcher.dispatch(run)
        return submission, run

    @staticmethod
    def _existing(lesson: Lesson) -> TestSubmission | None:
        return TestSubmission.objects.filter(lesson=lesson).first()

    def regrade(self, lesson: Lesson, submission_id) -> GraphRun:
        """Grade a failed submission again on the answers it already has."""
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
            submission = self.get(lesson, submission_id)
            if submission.status != TestSubmission.Status.FAILED:
                raise NotFailed()
            if has_active_run(lesson):
                raise RunInProgress()
            TestSubmission.objects.filter(pk=submission.pk).update(status=TestSubmission.Status.GRADING, error="")
            run = self._grading_run(lesson, submission)
        self.dispatcher.dispatch(run)
        return run

    def get(self, lesson: Lesson, submission_id) -> TestSubmission:
        try:
            return TestSubmission.objects.get(pk=submission_id, lesson=lesson)
        except (TestSubmission.DoesNotExist, ValueError, ValidationError):
            raise SubmissionNotFound() from None

    def current(self, lesson: Lesson) -> TestSubmission:
        """The lesson's one submission."""
        submission = TestSubmission.objects.filter(lesson=lesson).first()
        if submission is None:
            raise SubmissionNotFound()
        return submission

    def _shown(self, question: dict) -> dict:
        public = public_question(question)
        return {key: public[key] for key in self.SHOWN if key in public}

    @staticmethod
    def _grading_run(lesson: Lesson, submission: TestSubmission) -> GraphRun:
        return GraphRun.objects.create(
            lesson=lesson,
            graph=GraphRun.Graph.GRADE_TEST,
            trigger=GraphRun.Trigger.GRADE,
            payload={"input": {"submission_id": str(submission.id)}},
        )

    @staticmethod
    def _questions(lesson: Lesson) -> list[dict]:
        questions = (lesson.final_test or {}).get("questions")
        if lesson.stage != Stage.READY or lesson.route == Route.MASTERY or not questions:
            raise WrongStage("The test can be taken once the lesson is ready.")
        return questions

    def _clean(self, questions: list[dict], answers) -> dict:
        if not isinstance(answers, dict):
            raise InvalidAnswers("Send the answers as an object of question id → answer.")
        unknown = sorted(set(answers) - {q["id"] for q in questions})
        if unknown:
            raise InvalidAnswers(f"Unknown question ids: {', '.join(unknown)}.")
        for qid, value in answers.items():
            if isinstance(value, bool) or not (value is None or isinstance(value, (int, float, str))):
                raise InvalidAnswers(f"The answer to {qid} must be a number or text.")
            if isinstance(value, str) and len(value) > self.MAX_ANSWER_CHARS:
                raise InvalidAnswers(f"The answer to {qid} is longer than {self.MAX_ANSWER_CHARS} characters.")
        return dict(answers)

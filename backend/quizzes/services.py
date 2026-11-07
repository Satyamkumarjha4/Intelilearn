"""The use cases behind the quick quiz API. Views parse and format; these decide.

`QuickQuizService` makes a quiz (and asks the action gate first, so a refusal creates nothing), retakes it, deletes it
and turns a topic quiz's result into a lesson. `CalibrationService` runs the five-question walk that finds a level. The
attempts at a quiz are in `attempts.py`.
"""

import uuid
from dataclasses import dataclass

from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError

from graph.ladder import AdaptiveLadder
from graph.questions.traits import TopicTraits
from graph.quiz_config import QuizConfig, QuizConfigError
from lessons.effects import RunEffects
from lessons.errors import LessonNotConfigured, RunInProgress, WrongStage
from lessons.metering import ActionGate, ActionMetering, AuthorizationSettlement, MeteredAction, RunOutcome
from lessons.models import FlowSettings, GraphRun
from lessons.services import LessonService, RunDispatcher, TaskQueue, has_active_run
from llm_registry.resolver import RegistryResolver

from .erasure import QuizErasure
from .errors import NoQuestionLeft, NoTopicQuiz, NotTheCurrentQuestion, SourceMissing
from .models import QuickQuiz, QuickQuizAttempt, QuickQuizSource
from .sources import QuizSources, QuizTitle
from .stages import QuizStage
from .traits import TopicTraitsService


@dataclass(frozen=True)
class Created:
    quiz: QuickQuiz
    attempt: QuickQuizAttempt
    run: GraphRun


@dataclass(frozen=True)
class Retaken:
    attempt: QuickQuizAttempt
    run: GraphRun | None  # the run writing the questions, if the attempt is still generating
    created: bool  # false when the open attempt was returned instead


class QuickQuizService:
    #: the steps a quiz needs a model for, by how its level is found
    NODES = ("test.generate",)
    CALIBRATION_NODES = ("diagnostic.generate",)

    def __init__(
        self,
        queue: TaskQueue | None = None,
        resolver: RegistryResolver | None = None,
        gate: ActionGate | None = None,
        sources: QuizSources | None = None,
        traits: TopicTraitsService | None = None,
        erasure: QuizErasure | None = None,
        lessons: LessonService | None = None,
    ):
        self.metering = ActionMetering(gate)
        self.effects = RunEffects(settlement=AuthorizationSettlement(gate))
        self.dispatcher = RunDispatcher(queue, self.effects)
        self.resolver = resolver or RegistryResolver()
        self.sources = sources or QuizSources()
        self.traits = traits or TopicTraitsService()
        self.erasure = erasure or QuizErasure()
        self._lessons = lessons
        self._queue, self._gate = queue, gate

    @property
    def lessons(self) -> LessonService:
        if self._lessons is None:
            self._lessons = LessonService(queue=self._queue, gate=self._gate)
        return self._lessons

    # --- making a quiz -------------------------------------------------------------------------------------------

    def create(self, user, *, source: dict, num_questions, types, level, idempotency_key: str = "") -> Created:
        """A new quiz with its first attempt waiting for its questions, and the run that writes them. The rules of the
        request are all checked before the gate is asked, and the gate before the first row, so a refusal creates
        nothing."""
        settings_snapshot = FlowSettings.load().snapshot()
        topic, lessons, traits = self._source(user, source, settings_snapshot)
        config = self._config(num_questions, types, level, traits, source["type"])
        rows = (
            self.sources.rows(lessons, config, max_lessons=settings_snapshot["quiz_max_source_lessons"])
            if lessons
            else []
        )
        snapshot = self.resolver.snapshot()
        self.require_models(snapshot, config)
        title = QuizTitle.of([lesson.topic for lesson in lessons]) if lessons else topic
        quiz_id, attempt_id = uuid.uuid4(), uuid.uuid4()
        authorization = self.metering.authorize(
            user,
            MeteredAction.QUIZ_CREATE,
            size={
                "num_questions": config.num_questions,
                "source_type": source["type"],
                "sources": len(rows),
                "level_mode": config.level_mode,
                "has_subjective": config.has_subjective,
            },  # fmt: skip
            subject_id=quiz_id,
            client_key=idempotency_key,
        )
        keys = [str(lesson.pk) for lesson in lessons] if lessons else [topic]
        with self.metering.guard(authorization), transaction.atomic():
            quiz = QuickQuiz.objects.create(
                id=quiz_id,
                owner=user,
                source_type=source["type"],
                topic=title,
                config={**config.as_dict(), "traits": traits.as_dict() if traits else None},
                config_hash=config.hash(source["type"], keys),
                config_snapshot=snapshot.to_json(),
                settings_snapshot=settings_snapshot,
            )
            for row in rows:
                QuickQuizSource.objects.create(
                    quiz=quiz,
                    lesson=row.lesson,
                    lesson_ref=row.lesson.pk,
                    title=row.lesson.topic,
                    level=row.level.value,
                    share=row.share,
                )
            attempt = QuickQuizAttempt.objects.create(
                id=attempt_id, quiz=quiz, attempt_no=1, status=QuickQuizAttempt.Status.GENERATING, questions=[]
            )
            run = GraphRun.objects.create(
                quick_quiz=quiz,
                graph=GraphRun.Graph.QUICK_QUIZ,
                trigger=GraphRun.Trigger.START,
                payload={"input": {"attempt_id": str(attempt.id)}, **self.metering.payload(authorization)},
            )
        self.dispatcher.dispatch(run)
        return Created(quiz, attempt, run)

    def _source(self, user, source: dict, settings_snapshot: dict):
        """→ (the topic, the lessons, what is known of the topic). A topic is judged by the cheap cached call; lessons
        are
        read from their plans, with no model."""
        if source["type"] == QuickQuiz.SourceType.TOPIC:
            topic = " ".join(str(source["topic"]).split())
            return topic, [], self.traits.of(topic).traits
        lessons = self.sources.lessons(
            user, list(source["lesson_ids"]), max_lessons=settings_snapshot["quiz_max_source_lessons"]
        )
        return "", lessons, TopicTraits.of_lessons([(lesson.plan, lesson.pages) for lesson in lessons])

    @staticmethod
    def _config(num_questions, types, level, traits, source_type: str) -> QuizConfig:
        try:
            return QuizConfig.validate(
                num_questions=num_questions, types=types, level=level, traits=traits, source_type=source_type
            )
        except QuizConfigError as exc:
            raise ValidationError({exc.field: [exc.message]}) from exc

    def require_models(self, snapshot, config: QuizConfig) -> None:
        """Every step the quiz needs has a model, or it would fail at once."""
        needed = [*self.NODES, *(self.CALIBRATION_NODES if config.level_mode == "calibration" else ())]
        for key in needed:
            node = snapshot.node(key)
            if not node.enabled or not node.chain:
                raise LessonNotConfigured(
                    f"No AI model is bound to '{key}'. An admin must bind one in the model registry first."
                )

    # --- retaking ------------------------------------------------------------------------------------------------

    def retake(self, quiz: QuickQuiz, idempotency_key: str = "") -> Retaken:
        """A new attempt with new questions, or the one that is open (`quiz.retake` is asked of the gate only for a new
        one). The quiz keeps its settings and its level."""
        run = None
        with transaction.atomic():
            quiz = QuickQuiz.objects.select_for_update().get(pk=quiz.pk)
            if quiz.stage != QuizStage.READY:
                raise WrongStage("The quiz can be taken again once it is ready.")
            if (open_attempt := quiz.attempts.filter(status__in=QuickQuizAttempt.OPEN).first()) is not None:
                return Retaken(open_attempt, self.generating_run(open_attempt), created=False)
            if quiz.sources.filter(lesson__isnull=True).exists():
                raise SourceMissing()
            attempt_id = uuid.uuid4()
            number = (quiz.attempts.order_by("-attempt_no").values_list("attempt_no", flat=True).first() or 0) + 1
            authorization = self.metering.authorize(
                quiz.owner, MeteredAction.QUIZ_RETAKE,
                size={"num_questions": quiz.config["num_questions"], "source_type": quiz.source_type},
                subject_id=attempt_id, client_key=idempotency_key,
            )  # fmt: skip
            with self.metering.guard(authorization):
                attempt = QuickQuizAttempt.objects.create(
                    id=attempt_id, quiz=quiz, attempt_no=number, status=QuickQuizAttempt.Status.GENERATING, questions=[]
                )
                run = GraphRun.objects.create(
                    quick_quiz=quiz,
                    graph=GraphRun.Graph.QUICK_QUIZ,
                    trigger=GraphRun.Trigger.RETAKE,
                    payload={"input": {"attempt_id": str(attempt.id)}, **self.metering.payload(authorization)},
                )
        self.dispatcher.dispatch(run)
        return Retaken(attempt, run, created=True)

    @staticmethod
    def generating_run(attempt: QuickQuizAttempt) -> GraphRun | None:
        if attempt.status != QuickQuizAttempt.Status.GENERATING:
            return None
        runs = GraphRun.objects.filter(quick_quiz=attempt.quiz, graph=GraphRun.Graph.QUICK_QUIZ)
        return runs.filter(payload__input__attempt_id=str(attempt.id)).order_by("-created_at").first()

    # --- a lesson from a result ----------------------------------------------------------------------------------

    def create_lesson(self, quiz: QuickQuiz, attempt_id, idempotency_key: str = ""):
        """ "Create a lesson for this": a lesson about the quiz's topic whose level is found from the result (the quiz's
        level moved by how it went). Only a topic quiz can: a quiz from lessons sends the learner back to them."""
        if quiz.source_type != QuickQuiz.SourceType.TOPIC:
            raise NoTopicQuiz()
        attempt = (
            QuickQuizAttempt.objects.filter(pk=attempt_id, quiz=quiz, status=QuickQuizAttempt.Status.GRADED).first()
            if self._is_uuid(attempt_id)
            else None
        )
        if attempt is None:
            raise NotFound()
        return self.lessons.create(
            quiz.owner,
            quiz.topic,
            idempotency_key=idempotency_key,
            entry="quiz_result",
            origin="quiz_result",
            recommended_from={"quiz_id": str(quiz.pk), "attempt_id": str(attempt.pk)},
        )

    @staticmethod
    def _is_uuid(value) -> bool:
        try:
            uuid.UUID(str(value))
        except ValueError:
            return False
        return True

    # --- deleting ------------------------------------------------------------------------------------------------

    def delete(self, quiz: QuickQuiz) -> list:
        """Cancel whatever is running, settle the open authorization as cancelled, erase what the cascade does not reach
        (the LangGraph checkpoints, the model calls), then remove the quiz with its attempts and its calibration.
        Erasing
        comes first, so if it fails the quiz is still there and the delete can be repeated."""
        active = GraphRun.objects.for_subject(quiz).filter(status__in=[GraphRun.Status.QUEUED, GraphRun.Status.RUNNING])
        cancelled = list(active.values_list("pk", flat=True))
        active.update(status=GraphRun.Status.CANCELLED)
        self.metering.settle_open(quiz, RunOutcome.CANCELLED)
        self.erasure.erase(quiz)
        quiz.delete()
        return cancelled


class CalibrationService:
    """The calibration walk (plan §9.4): one question at a time from the pool, harder after a right answer and easier
    after
    a wrong one, five questions, driven by the API with no model call. The server holds the pool and the walk; the
    learner
    is shown a question with no band, no answer and no hint of what comes next."""

    def __init__(self, queue: TaskQueue | None = None, gate: ActionGate | None = None):
        self.metering = ActionMetering(gate)
        self.dispatcher = RunDispatcher(queue, RunEffects(settlement=AuthorizationSettlement(gate)))

    #: what a learner is shown of a pool question: nothing that gives the band or the answer away
    SHOWN = ("id", "question", "options")

    def current(self, quiz: QuickQuiz) -> dict:
        """The question to answer now, or `{done: true, level}` once the five are answered."""
        ladder = self._ladder(quiz)
        walk = self._walk(quiz)
        if ladder.done(self._answers(walk)):
            return self._finished(quiz, ladder, walk)
        if quiz.stage != QuizStage.AWAITING_CALIBRATION or not (quiz.calibration or {}).get("pool"):
            raise WrongStage("The quiz is not waiting for calibration answers.")
        question = ladder.pick(quiz.calibration["pool"], [step["question_id"] for step in walk], self._answers(walk))
        return {"done": False, "step": len(walk) + 1, "total": ladder.QUESTIONS, "question": self._shown(question)}

    def answer(self, quiz: QuickQuiz, question_id: str, answer) -> dict:
        """Mark one answer, move the ladder, and either give the next question or, after the last, resume the quiz"
        " once."""
        run = None
        with transaction.atomic():
            quiz = QuickQuiz.objects.select_for_update().get(pk=quiz.pk)
            ladder, walk = self._ladder(quiz), self._walk(quiz)
            if ladder.done(self._answers(walk)):
                raise NoQuestionLeft()
            if quiz.stage != QuizStage.AWAITING_CALIBRATION or not (quiz.calibration or {}).get("pool"):
                raise WrongStage("The quiz is not waiting for calibration answers.")
            pool = quiz.calibration["pool"]
            question = ladder.pick(pool, [step["question_id"] for step in walk], self._answers(walk))
            if question_id != question["id"]:
                raise NotTheCurrentQuestion()
            right = isinstance(answer, int) and not isinstance(answer, bool) and answer == question["correct_index"]
            step = {"question_id": question["id"], "band": question["band"], "correct": right}
            walk = [*walk, step]
            quiz.record(calibration={**quiz.calibration, "walk": walk})
            if ladder.done(self._answers(walk)):
                if has_active_run(quiz):
                    raise RunInProgress()
                run = GraphRun.objects.create(
                    quick_quiz=quiz,
                    graph=GraphRun.Graph.QUICK_QUIZ,
                    trigger=GraphRun.Trigger.RESUME_CALIBRATION,
                    payload={"resume": True, **self.metering.carry(quiz)},
                )
        if run:
            self.dispatcher.dispatch(run)
            return self._finished(quiz, ladder, walk)
        return self.current(quiz)

    # --- helpers -------------------------------------------------------------------------------------------------

    def _ladder(self, quiz: QuickQuiz) -> AdaptiveLadder:
        return AdaptiveLadder((quiz.settings_snapshot or {}).get("calibration_questions", AdaptiveLadder.QUESTIONS))

    @staticmethod
    def _walk(quiz: QuickQuiz) -> list[dict]:
        return list((quiz.calibration or {}).get("walk") or [])

    @staticmethod
    def _answers(walk: list[dict]) -> list[bool]:
        return [step["correct"] for step in walk]

    def _shown(self, question: dict) -> dict:
        return {key: question[key] for key in self.SHOWN}

    @staticmethod
    def _finished(quiz: QuickQuiz, ladder: AdaptiveLadder, walk: list[dict]) -> dict:
        level = ladder.level([step["correct"] for step in walk])
        return {"done": True, "level": level.value}

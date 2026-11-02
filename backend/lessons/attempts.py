"""A learner's attempts at a lesson's test: starting one, answering it a question at a time, sealing it, and what
follows from its score. Split out of `services.py`, where it was `SubmissionService` (the one submission).

An attempt is a `TestSubmission` row. Attempt 1 is part of the lesson: it starts at once from the questions the lesson
was built with, its first set on the record (`QuestionBank.first_set`). Attempt 2 and later always generate a
fresh set (`question_bank` graph), after the action gate has been asked for `test.retake`; the row waits as
`generating` and starts as `in_progress` when its questions are ready. At most one attempt is open at a time.

A lesson attempt is objective only, so submitting grades it in full in the same request. Only a legacy attempt with
open-ended questions queues `grade_test`; both call `AttemptOutcome`, the one rule for what a score leads to.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import NamedTuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from graph.grading import AnswerGrader, ScoreCard
from graph.questions import LessonTestBlueprint
from graph.schemas import public_question
from graph.scoring import AttemptTrend

from .bank import QuestionBank
from .effects import RunEffects
from .errors import (
    AttemptSealed,
    InvalidAnswers,
    NotFailed,
    QuestionLocked,
    RetakeLimitReached,
    RunInProgress,
    SubmissionNotFound,
    WrongStage,
)
from .metering import ActionGate, ActionMetering, AuthorizationSettlement, MeteredAction
from .models import GraphRun, Lesson, Route, Stage, TestSubmission
from .outcome import AttemptOutcome, Decision
from .services import RunDispatcher, TaskQueue, has_active_run


@dataclass(frozen=True)
class Started:
    attempt: TestSubmission
    run: GraphRun | None  # the run that is preparing a retake's questions, if the attempt is generating
    created: bool  # false when the open attempt was returned instead


class Submitted(NamedTuple):
    attempt: TestSubmission
    run: GraphRun | None  # the grading run of a legacy attempt with open-ended answers


class AttemptQuestions:
    """The questions of an attempt as the learner may see them: no answer, marking scheme, explanation or concept
    (`public_question` is the allowlist). An attempt that is still open serves them through `GET /test` only."""

    #: what the test screen needs of `public_question`; the concept and difficulty are labels for the grader and the
    #: report, not for the person answering
    SHOWN = ("id", "type", "question", "marks", "options", "unit", "decimal_precision", "language", "starter_code")

    @classmethod
    def one(cls, question: dict) -> dict:
        public = public_question(question)
        return {key: public[key] for key in cls.SHOWN if key in public}

    @classmethod
    def of(cls, attempt: TestSubmission) -> list[dict]:
        return [cls.one(q) for q in attempt.questions]

    @classmethod
    def of_sealed(cls, attempt: TestSubmission) -> list[dict]:
        """For the read-only result: once the attempt is over the learner is shown the solutions anyway."""
        return [] if attempt.is_open else cls.of(attempt)


class AnswerCleaner:
    """The checks on what a learner sends as an answer (a number, text, a list of option numbers or nothing)."""

    MAX_ANSWER_CHARS = 10_000
    MAX_SELECTED = 12  # a multiple-select question has at most 6 options

    def one(self, qid: str, value):
        if isinstance(value, list):  # the options picked in a multiple-select question
            if len(value) > self.MAX_SELECTED or not all(type(item) is int for item in value):
                raise InvalidAnswers(f"The answer to {qid} must be a short list of option numbers.")
            return value
        if isinstance(value, bool) or not (value is None or isinstance(value, (int, float, str))):
            raise InvalidAnswers(f"The answer to {qid} must be a number or text.")
        if isinstance(value, str) and len(value) > self.MAX_ANSWER_CHARS:
            raise InvalidAnswers(f"The answer to {qid} is longer than {self.MAX_ANSWER_CHARS} characters.")
        return value

    def many(self, questions: list[dict], answers) -> dict:
        if not isinstance(answers, dict):
            raise InvalidAnswers("Send the answers as an object of question id → answer.")
        unknown = sorted(set(answers) - {q["id"] for q in questions})
        if unknown:
            raise InvalidAnswers(f"Unknown question ids: {', '.join(unknown)}.")
        return {qid: self.one(qid, value) for qid, value in answers.items()}


class AttemptService:
    RETAKE_WINDOW = timedelta(hours=24)
    DEFAULT_RETAKES_PER_DAY = 3

    def __init__(
        self,
        queue: TaskQueue | None = None,
        grader: AnswerGrader | None = None,
        cards: ScoreCard | None = None,
        gate: ActionGate | None = None,
        outcome: AttemptOutcome | None = None,
        cleaner: AnswerCleaner | None = None,
        bank: QuestionBank | None = None,
    ):
        self.metering = ActionMetering(gate)
        self.dispatcher = RunDispatcher(queue, RunEffects(settlement=AuthorizationSettlement(gate)))
        self.grader = grader or AnswerGrader()
        self.cards = cards or ScoreCard()
        self.outcome = outcome or AttemptOutcome()
        self.cleaner = cleaner or AnswerCleaner()
        self.bank = bank or QuestionBank()

    # --- reading -------------------------------------------------------------------------------------------------

    def for_learner(self, lesson: Lesson) -> dict:
        """The test to take: the open attempt's questions without answers or marking schemes, or none (and the number
        of the attempt a start would make). No side effects."""
        self._testable(lesson)
        open_attempt = self._open(lesson)
        latest = self._latest(lesson)
        questions = (
            open_attempt.questions if open_attempt and open_attempt.status == TestSubmission.Status.IN_PROGRESS else []
        )
        return {
            "questions": [AttemptQuestions.one(q) for q in questions],
            "total_marks": sum(q["marks"] for q in questions),
            "attempt": None if open_attempt is None else self._ref(open_attempt),
            "answers": {} if open_attempt is None else open_attempt.answers,
            "next_attempt_no": (latest.attempt_no + 1) if latest else 1,
            "submission": None if latest is None else self._ref(latest),
        }

    def history(self, lesson: Lesson) -> dict:
        attempts = list(TestSubmission.objects.filter(lesson=lesson).order_by("attempt_no"))
        graded = [a for a in attempts if a.status == TestSubmission.Status.GRADED and a.available]
        trend = AttemptTrend().of(
            [{"attempt_no": a.attempt_no, "awarded": a.awarded, "available": a.available} for a in graded]
        )
        return {"attempts": [self._summary(a) for a in attempts], "trend": trend}

    def get(self, lesson: Lesson, attempt_id) -> TestSubmission:
        try:
            return TestSubmission.objects.get(pk=attempt_id, lesson=lesson)
        except (TestSubmission.DoesNotExist, ValueError, ValidationError):
            raise SubmissionNotFound() from None

    def current(self, lesson: Lesson) -> TestSubmission:
        """The latest attempt."""
        attempt = self._latest(lesson)
        if attempt is None:
            raise SubmissionNotFound()
        return attempt

    def shown_questions(self, attempt: TestSubmission) -> list[dict]:
        return AttemptQuestions.of(attempt)

    # --- starting ------------------------------------------------------------------------------------------------

    def start(self, lesson: Lesson, idempotency_key: str = "") -> Started:
        """Open the next attempt, or return the one that is open. The first starts at once; every later one generates
        its questions (`test.retake` is asked of the gate first, so a refusal creates nothing)."""
        run = None
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
            self._testable(lesson)
            if (open_attempt := self._open(lesson)) is not None:
                return Started(open_attempt, self._generating_run(open_attempt), created=False)
            number = (self._latest(lesson).attempt_no + 1) if self._latest(lesson) else 1
            if number == 1:
                attempt = TestSubmission.objects.create(
                    lesson=lesson,
                    attempt_no=1,
                    status=TestSubmission.Status.IN_PROGRESS,
                    questions=self._old_test(lesson),
                )
            else:
                attempt, run = self._begin_retake(lesson, number, idempotency_key)
        if run:
            self.dispatcher.dispatch(run)
        return Started(attempt, run, created=True)

    def _begin_retake(self, lesson: Lesson, number: int, idempotency_key: str) -> tuple[TestSubmission, GraphRun]:
        self._check_daily_limit(lesson)
        attempt_id = uuid.uuid4()
        authorization = self.metering.authorize(
            lesson.owner,
            MeteredAction.TEST_RETAKE,
            size={"question_count": LessonTestBlueprint.SIZE, "attempt_no": number},
            subject_id=attempt_id,
            client_key=idempotency_key,
        )
        with self.metering.guard(authorization):
            attempt = TestSubmission.objects.create(
                id=attempt_id, lesson=lesson, attempt_no=number, status=TestSubmission.Status.GENERATING, questions=[]
            )
            run = GraphRun.objects.create(
                lesson=lesson,
                graph=GraphRun.Graph.QUESTION_BANK,
                trigger=GraphRun.Trigger.RETAKE,
                payload={"input": {"attempt_id": str(attempt.id)}, **self.metering.payload(authorization)},
            )
        return attempt, run

    def _check_daily_limit(self, lesson: Lesson) -> None:
        limit = (lesson.settings_snapshot or {}).get("retakes_per_day", self.DEFAULT_RETAKES_PER_DAY)
        recent = TestSubmission.objects.filter(
            lesson=lesson, attempt_no__gte=2, started_at__gte=timezone.now() - self.RETAKE_WINDOW
        )
        if recent.count() >= limit:
            raise RetakeLimitReached()

    # --- answering -----------------------------------------------------------------------------------------------

    def save_answer(self, lesson: Lesson, attempt_id, question_id: str, value) -> TestSubmission:
        """Save one answer and lock that question: forward-only, enforced here, so a refresh resumes and the time
        taken is the server's. A blank answer locks it too (the learner moved on without answering)."""
        with transaction.atomic():
            attempt = self._locked(lesson, attempt_id)
            self._require_open(attempt)
            if question_id not in {q["id"] for q in attempt.questions}:
                raise InvalidAnswers(f"Unknown question id: {question_id}.")
            if question_id in attempt.answers:
                raise QuestionLocked()
            answers = {**attempt.answers, question_id: self.cleaner.one(question_id, value)}
            TestSubmission.objects.filter(pk=attempt.pk, status=TestSubmission.Status.IN_PROGRESS).update(
                answers=answers
            )
            attempt.answers = answers
        return attempt

    # --- submitting ----------------------------------------------------------------------------------------------

    def submit(self, lesson: Lesson, attempt_id, answers=None) -> Submitted:
        """Seal the attempt (missing answers are blank and score 0) and mark it. `answers` may add answers to
        questions that are not locked yet (the last card is sent with the submit)."""
        with transaction.atomic():
            attempt = self._locked(lesson, attempt_id)
            self._require_open(attempt)
            extra = self.cleaner.many(attempt.questions, answers or {})
            merged = {**{q: v for q, v in extra.items() if q not in attempt.answers}, **attempt.answers}
            run = self._seal(lesson, attempt, merged)
        if run:
            self.dispatcher.dispatch(run)
        return Submitted(attempt, run)

    def _seal(self, lesson: Lesson, attempt: TestSubmission, answers: dict) -> GraphRun | None:
        """Mark the answers and close the attempt. A lesson attempt is graded in full here; one with open-ended
        questions is marked as far as it can be and queued for `grade_test`."""
        questions = attempt.questions
        pending = bool(self.cards.open_items(questions, answers))
        card = self.cards.build(questions, answers, self.grader.grade_all(questions, answers), None if pending else {})
        blank = bool(questions) and all(self.cards.is_blank(answers.get(q["id"])) for q in questions)
        decision = (
            Decision("", None) if pending else self.outcome.decide(lesson, attempt.attempt_no, card, all_blank=blank)
        )
        attempt.seal(
            answers=answers,
            status=TestSubmission.Status.GRADING if pending else TestSubmission.Status.GRADED,
            result=card,
            band=decision.band,
            followup=decision.followup,
            all_blank=blank,
            now=timezone.now(),
        )
        return self._grading_run(lesson, attempt) if pending else None

    def regrade(self, lesson: Lesson, attempt_id) -> GraphRun:
        """Grade a failed attempt again on the answers it already has. Only a legacy attempt can be in this state."""
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
            attempt = self.get(lesson, attempt_id)
            if attempt.status != TestSubmission.Status.FAILED:
                raise NotFailed()
            if has_active_run(lesson):
                raise RunInProgress()
            TestSubmission.objects.filter(pk=attempt.pk).update(status=TestSubmission.Status.GRADING, error="")
            run = self._grading_run(lesson, attempt)
        self.dispatcher.dispatch(run)
        return run

    # --- helpers -------------------------------------------------------------------------------------------------

    def _testable(self, lesson: Lesson) -> None:
        if lesson.stage != Stage.READY or lesson.route == Route.MASTERY:
            raise WrongStage("The test can be taken once the lesson is ready.")
        if not self._old_test(lesson) and not TestSubmission.objects.filter(lesson=lesson).exists():
            raise WrongStage("The test can be taken once the lesson is ready.")

    def _old_test(self, lesson: Lesson) -> list[dict]:
        """The questions the lesson was built with: attempt 1."""
        return self.bank.first_set(lesson)

    @staticmethod
    def _open(lesson: Lesson) -> TestSubmission | None:
        return TestSubmission.objects.filter(lesson=lesson, status__in=TestSubmission.OPEN).first()

    @staticmethod
    def _latest(lesson: Lesson) -> TestSubmission | None:
        return TestSubmission.objects.filter(lesson=lesson).order_by("-attempt_no").first()

    def _locked(self, lesson: Lesson, attempt_id) -> TestSubmission:
        try:
            return TestSubmission.objects.select_for_update().get(pk=attempt_id, lesson=lesson)
        except (TestSubmission.DoesNotExist, ValueError, ValidationError):
            raise SubmissionNotFound() from None

    @staticmethod
    def _require_open(attempt: TestSubmission) -> None:
        if attempt.status == TestSubmission.Status.GENERATING:
            raise WrongStage("The questions are still being prepared.")
        if attempt.status != TestSubmission.Status.IN_PROGRESS:
            raise AttemptSealed()

    @staticmethod
    def _generating_run(attempt: TestSubmission) -> GraphRun | None:
        if attempt.status != TestSubmission.Status.GENERATING:
            return None
        runs = GraphRun.objects.filter(lesson=attempt.lesson, graph=GraphRun.Graph.QUESTION_BANK)
        return runs.filter(payload__input__attempt_id=str(attempt.id)).order_by("-created_at").first()

    @staticmethod
    def _ref(attempt: TestSubmission) -> dict:
        return {
            "id": str(attempt.id), "attempt_no": attempt.attempt_no, "status": attempt.status,
            "started_at": attempt.started_at, "submitted_at": attempt.submitted_at,
        }  # fmt: skip

    @staticmethod
    def _summary(attempt: TestSubmission) -> dict:
        percent = round(100 * attempt.awarded / attempt.available) if attempt.available else None
        return {
            "id": str(attempt.id), "attempt_no": attempt.attempt_no, "status": attempt.status,
            "awarded": attempt.awarded, "available": attempt.available, "percent": percent, "band": attempt.band,
            "duration_s": attempt.duration_s, "submitted_at": attempt.submitted_at,
        }  # fmt: skip

    @staticmethod
    def _grading_run(lesson: Lesson, attempt: TestSubmission) -> GraphRun:
        return GraphRun.objects.create(
            lesson=lesson,
            graph=GraphRun.Graph.GRADE_TEST,
            trigger=GraphRun.Trigger.GRADE,
            payload={"input": {"submission_id": str(attempt.id)}},
        )

"""A learner's attempts at a quick quiz: answering one question at a time, sealing the attempt, and what it scored.

The same rules as a lesson test's attempts (`lessons/attempts.py`), on a quiz: the server locks each question as it is
answered (forward only, so a refresh resumes and the time taken is the server's), a sealed attempt never changes, and an
attempt with only questions that have one right answer is graded in the same request. A quiz is the one place short and
long answers are asked, so an attempt with those is marked as far as it can be and queued for `grade_quiz`. Nothing here
asks the action gate: starting the first attempt is part of making the quiz, and a retake is asked for in
`QuickQuizService.retake`.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from graph.attempt_stores import QuizAttemptStore
from graph.grading import AnswerGrader, ScoreCard
from graph.scoring import AttemptTrend, ScoreBand
from lessons.activity import ActivityKind, ActivitySink, ActivitySinks
from lessons.attempts import AnswerCleaner, AttemptQuestions
from lessons.effects import RunEffects
from lessons.errors import (
    AttemptSealed,
    InvalidAnswers,
    NotFailed,
    QuestionLocked,
    RunInProgress,
    SubmissionNotFound,
    WrongStage,
)
from lessons.metering import ActionGate, AuthorizationSettlement
from lessons.models import GraphRun
from lessons.services import RunDispatcher, TaskQueue, has_active_run

from .models import QuickQuiz, QuickQuizAttempt
from .stages import QuizStage


class QuizAttemptService:
    def __init__(
        self,
        queue: TaskQueue | None = None,
        grader: AnswerGrader | None = None,
        cards: ScoreCard | None = None,
        gate: ActionGate | None = None,
        cleaner: AnswerCleaner | None = None,
        store: QuizAttemptStore | None = None,
        activity: ActivitySink | None = None,
    ):
        self.activity = ActivitySinks.guarded(activity)
        self.dispatcher = RunDispatcher(queue, RunEffects(settlement=AuthorizationSettlement(gate)))
        self.grader = grader or AnswerGrader()
        self.cards = cards or ScoreCard()
        self.cleaner = cleaner or AnswerCleaner()
        self.store = store or QuizAttemptStore()

    # --- reading -------------------------------------------------------------------------------------------------

    def get(self, quiz: QuickQuiz, attempt_id) -> QuickQuizAttempt:
        try:
            return QuickQuizAttempt.objects.get(pk=attempt_id, quiz=quiz)
        except (QuickQuizAttempt.DoesNotExist, ValueError, ValidationError):
            raise SubmissionNotFound() from None

    @staticmethod
    def open(quiz: QuickQuiz) -> QuickQuizAttempt | None:
        return quiz.attempts.filter(status__in=QuickQuizAttempt.OPEN).first()

    def history(self, quiz: QuickQuiz) -> dict:
        """Every attempt, oldest first, and the trend of the graded ones. Attempts are compared only with this quiz's
        own: the same settings, the same kinds of question, the same level."""
        attempts = list(quiz.attempts.order_by("attempt_no"))
        graded = [a for a in attempts if a.status == QuickQuizAttempt.Status.GRADED and a.available]
        trend = AttemptTrend().of(
            [{"attempt_no": a.attempt_no, "awarded": a.awarded, "available": a.available} for a in graded]
        )
        return {"attempts": [self.summary(a) for a in attempts], "trend": trend}

    @staticmethod
    def summary(attempt: QuickQuizAttempt) -> dict:
        percent = round(100 * attempt.awarded / attempt.available) if attempt.available else None
        return {
            "id": str(attempt.id), "attempt_no": attempt.attempt_no, "status": attempt.status,
            "awarded": attempt.awarded, "available": attempt.available, "percent": percent, "band": attempt.band,
            "duration_s": attempt.duration_s, "submitted_at": attempt.submitted_at,
        }  # fmt: skip

    @staticmethod
    def shown_questions(attempt: QuickQuizAttempt) -> list[dict]:
        """The questions of an attempt in progress, without answers, marking schemes, explanations or the lesson each is
        about. Nothing before the attempt has started."""
        if attempt.status != QuickQuizAttempt.Status.IN_PROGRESS:
            return []
        return [AttemptQuestions.one(q) for q in attempt.questions]

    @staticmethod
    def sealed_questions(attempt: QuickQuizAttempt) -> list[dict]:
        """For the read-only result: once the attempt is over the learner is shown the solutions anyway."""
        return [] if attempt.is_open else [AttemptQuestions.one(q) for q in attempt.questions]

    # --- answering -----------------------------------------------------------------------------------------------

    def save_answer(self, quiz: QuickQuiz, attempt_id, question_id: str, value) -> QuickQuizAttempt:
        """Save one answer and lock that question: forward-only, enforced here."""
        with transaction.atomic():
            attempt = self._locked(quiz, attempt_id)
            self._require_open(attempt)
            if question_id not in {q["id"] for q in attempt.questions}:
                raise InvalidAnswers(f"Unknown question id: {question_id}.")
            if question_id in attempt.answers:
                raise QuestionLocked()
            answers = {**attempt.answers, question_id: self.cleaner.one(question_id, value)}
            QuickQuizAttempt.objects.filter(pk=attempt.pk, status=QuickQuizAttempt.Status.IN_PROGRESS).update(
                answers=answers
            )
            attempt.answers = answers
        return attempt

    # --- submitting ----------------------------------------------------------------------------------------------

    def submit(self, quiz: QuickQuiz, attempt_id, answers=None) -> tuple[QuickQuizAttempt, GraphRun | None]:
        """Seal the attempt (missing answers are blank and score 0) and mark it. `answers` may add answers to questions
        that are not locked yet (the last card is sent with the submit). → the attempt, and the grading run if some
        answers need a judgement."""
        with transaction.atomic():
            attempt = self._locked(quiz, attempt_id)
            self._require_open(attempt)
            extra = self.cleaner.many(attempt.questions, answers or {})
            merged = {**{q: v for q, v in extra.items() if q not in attempt.answers}, **attempt.answers}
            run = self._seal(quiz, attempt, merged)
        if not attempt.all_blank:  # an attempt of only blank answers is no study (Phase 9's blank-attempt rule)
            self.activity.record(quiz.owner, ActivityKind.QUIZ_ATTEMPT, attempt.submitted_at)
        if run:
            self.dispatcher.dispatch(run)
        return attempt, run

    def _seal(self, quiz: QuickQuiz, attempt: QuickQuizAttempt, answers: dict) -> GraphRun | None:
        questions = attempt.questions
        pending = bool(self.cards.open_items(questions, answers))
        card = self.cards.build(questions, answers, self.grader.grade_all(questions, answers), None if pending else {})
        blank = bool(questions) and all(self.cards.is_blank(answers.get(q["id"])) for q in questions)
        score = card["score"]
        band = ""
        if not pending and score["available"] > 0:
            band = ScoreBand.of(score["awarded"], score["available"], self.store.thresholds(quiz)).value
        attempt.seal(
            answers=answers,
            status=QuickQuizAttempt.Status.GRADING if pending else QuickQuizAttempt.Status.GRADED,
            result=card,
            band=band,
            all_blank=blank,
            now=timezone.now(),
        )
        return self._grading_run(quiz, attempt) if pending else None

    def regrade(self, quiz: QuickQuiz, attempt_id) -> GraphRun:
        """Grade a failed attempt again on the answers it already has."""
        with transaction.atomic():
            quiz = QuickQuiz.objects.select_for_update().get(pk=quiz.pk)
            attempt = self.get(quiz, attempt_id)
            if attempt.status != QuickQuizAttempt.Status.FAILED:
                raise NotFailed()
            if has_active_run(quiz):
                raise RunInProgress()
            QuickQuizAttempt.objects.filter(pk=attempt.pk).update(status=QuickQuizAttempt.Status.GRADING, error="")
            run = self._grading_run(quiz, attempt)
        self.dispatcher.dispatch(run)
        return run

    # --- helpers -------------------------------------------------------------------------------------------------

    def _locked(self, quiz: QuickQuiz, attempt_id) -> QuickQuizAttempt:
        try:
            return QuickQuizAttempt.objects.select_for_update().get(pk=attempt_id, quiz=quiz)
        except (QuickQuizAttempt.DoesNotExist, ValueError, ValidationError):
            raise SubmissionNotFound() from None

    @staticmethod
    def _require_open(attempt: QuickQuizAttempt) -> None:
        if attempt.status == QuickQuizAttempt.Status.GENERATING:
            raise WrongStage("The questions are still being prepared.")
        if attempt.status != QuickQuizAttempt.Status.IN_PROGRESS:
            raise AttemptSealed()
        if attempt.quiz.stage == QuizStage.FAILED:
            raise WrongStage("This quiz could not be made.")

    @staticmethod
    def _grading_run(quiz: QuickQuiz, attempt: QuickQuizAttempt) -> GraphRun:
        return GraphRun.objects.create(
            quick_quiz=quiz,
            graph=GraphRun.Graph.GRADE_QUIZ,
            trigger=GraphRun.Trigger.GRADE,
            payload={"input": {"attempt_id": str(attempt.id)}},
        )

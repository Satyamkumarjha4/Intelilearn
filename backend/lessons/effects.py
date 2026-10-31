"""What else a run that did not finish leaves behind besides its own row.

A lesson's main flow fails the lesson (`Lesson.fail`, which leaves a ready lesson alone); a submitted test that was
being graded must not stay "grading" for ever, so its submission is marked failed and can be graded again (the
learner never answers twice); a retake whose questions could not be written leaves no attempt behind. Every run, of
any graph, also reports its end to the action gate (`AuthorizationSettlement`, lessons/metering.py).
"""

from typing import Protocol

from quizzes.models import QuickQuizAttempt

from .metering import AuthorizationSettlement
from .models import GraphRun, TestSubmission


class RunEffect(Protocol):
    def apply(self, run: GraphRun, message: str) -> None: ...


class SubmissionEffect:
    """The `grade_test` run for a submission ended without grading it."""

    def apply(self, run: GraphRun, message: str) -> None:
        submission_id = (run.payload.get("input") or {}).get("submission_id")
        TestSubmission.objects.filter(pk=submission_id, status=TestSubmission.Status.GRADING).update(
            status=TestSubmission.Status.FAILED, error=message
        )


class AttemptGenerationEffect:
    """A run that writes an attempt's questions (a lesson's retake, a quiz's first attempt or retake) ended without them
    (failed or stopped): the attempt that waited for them goes, so the attempt number is never used up and the learner
    starts again with a fresh authorization (T17). `attempts` is the model the attempt is a row of."""

    def __init__(self, attempts=TestSubmission):
        self.attempts = attempts

    def apply(self, run: GraphRun, message: str) -> None:
        attempt_id = (run.payload.get("input") or {}).get("attempt_id")
        self.attempts.objects.filter(pk=attempt_id, status=self.attempts.Status.GENERATING).delete()


class QuizAttemptEffect:
    """The `grade_quiz` run for a quiz attempt ended without grading it: the attempt is marked failed, so it is not
    "grading" for ever and can be graded again (the learner never answers twice)."""

    def apply(self, run: GraphRun, message: str) -> None:
        attempt_id = (run.payload.get("input") or {}).get("attempt_id")
        QuickQuizAttempt.objects.filter(pk=attempt_id, status=QuickQuizAttempt.Status.GRADING).update(
            status=QuickQuizAttempt.Status.FAILED, error=message
        )


class RunEffects:
    """The effect of a run that failed or was cancelled, by the graph it ran, and the report to the action gate."""

    def __init__(self, effects: dict[str, RunEffect] | None = None, settlement: AuthorizationSettlement | None = None):
        self.effects = (
            effects
            if effects is not None
            else {
                GraphRun.Graph.GRADE_TEST: SubmissionEffect(),
                GraphRun.Graph.QUESTION_BANK: AttemptGenerationEffect(),
                GraphRun.Graph.QUICK_QUIZ: AttemptGenerationEffect(QuickQuizAttempt),
                GraphRun.Graph.GRADE_QUIZ: QuizAttemptEffect(),
            }
        )
        self.settlement = settlement or AuthorizationSettlement()

    def on_stopped(self, run: GraphRun, message: str) -> None:
        if effect := self.effects.get(run.graph):
            effect.apply(run, message)
        self.settlement.on_stopped(run, message)

    def on_finished(self, run: GraphRun, *, ended: bool = False) -> None:
        """The run paused (`ended` false) or ran to its end (true)."""
        self.settlement.on_finished(run, ended=ended)

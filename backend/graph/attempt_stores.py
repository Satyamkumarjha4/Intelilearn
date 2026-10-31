"""Where the grading graph finds an attempt and saves its card (plan §9.7): the `AttemptStore` port.

A lesson's test attempt and a quick quiz's attempt are marked by one graph (`GradeAttemptGraphBuilder`, registered as
`grade_test` and `grade_quiz`). The graph does not know which it has: it asks its store to load the attempt, and to save
the finished `ScoreCard`. The lesson's store also decides the follow-up offer (`AttemptOutcome`); a quiz has no offer.
"""

from dataclasses import dataclass, field
from typing import Protocol

from django.utils import timezone

from lessons.models import Lesson, TestSubmission
from lessons.outcome import AttemptOutcome
from quizzes.models import QuickQuiz, QuickQuizAttempt

from .scoring import ScoreBand, Thresholds


@dataclass(frozen=True)
class LoadedAttempt:
    """What grading needs of an attempt, and the state keys that make the run's model calls attributable."""

    topic: str
    profile: dict
    snapshot: dict
    settings: dict
    questions: list[dict]
    answers: dict
    state: dict = field(default_factory=dict)  # more for the graph state (the quiz id)


class AttemptStore(Protocol):
    def load(self, state: dict) -> LoadedAttempt:
        """The attempt the run is about. Raises if it is not there."""

    def save(self, state: dict, card: dict) -> None:
        """The finished card, with the band it leads to, on the attempt that was being graded."""


class LessonAttemptStore:
    """A lesson's test attempt (`TestSubmission`): the run's input is `{lesson_id, submission_id}`."""

    def __init__(self, outcome: AttemptOutcome | None = None):
        self.outcome = outcome or AttemptOutcome()

    def load(self, state: dict) -> LoadedAttempt:
        lesson = Lesson.objects.select_related("owner__profile").get(pk=state["lesson_id"])
        submission = TestSubmission.objects.get(pk=state["submission_id"], lesson=lesson)
        return LoadedAttempt(
            topic=lesson.topic,
            profile={"preferred_language": lesson.owner.profile.preferred_language},
            snapshot=lesson.config_snapshot,
            settings=lesson.settings_snapshot,
            questions=submission.questions,
            answers=submission.answers,
        )

    def save(self, state: dict, card: dict) -> None:
        submission = TestSubmission.objects.select_related("lesson").get(pk=state["submission_id"])
        self.outcome.graded(submission, card)


class QuizAttemptStore:
    """A quick quiz's attempt (`QuickQuizAttempt`): the run's input is `{quiz_id, attempt_id}`. The band is read from
    the
    quiz's own thresholds and nothing follows from it."""

    DEFAULT_THRESHOLDS = Thresholds()

    def load(self, state: dict) -> LoadedAttempt:
        quiz = QuickQuiz.objects.select_related("owner__profile").get(pk=state["quiz_id"])
        attempt = QuickQuizAttempt.objects.get(pk=state["attempt_id"], quiz=quiz)
        return LoadedAttempt(
            topic=quiz.topic,
            profile={"preferred_language": quiz.owner.profile.preferred_language},
            snapshot=quiz.config_snapshot,
            settings=quiz.settings_snapshot,
            questions=attempt.questions,
            answers=attempt.answers,
            state={"quiz_id": str(quiz.id)},
        )

    def save(self, state: dict, card: dict) -> None:
        attempt = QuickQuizAttempt.objects.select_related("quiz").get(pk=state["attempt_id"])
        score = card["score"]
        thresholds = self.thresholds(attempt.quiz)
        band = ScoreBand.of(score["awarded"], score["available"], thresholds).value if score["available"] else ""
        QuickQuizAttempt.objects.filter(pk=attempt.pk, status=QuickQuizAttempt.Status.GRADING).update(
            result=card,
            status=QuickQuizAttempt.Status.GRADED,
            error="",
            graded_at=timezone.now(),
            awarded=score["awarded"],
            available=score["available"],
            band=band,
        )

    def thresholds(self, quiz: QuickQuiz) -> Thresholds:
        snapshot = quiz.settings_snapshot or {}
        return Thresholds(
            fail_below=snapshot.get("band_fail_below", self.DEFAULT_THRESHOLDS.fail_below),
            excellent_above=snapshot.get("band_excellent_above", self.DEFAULT_THRESHOLDS.excellent_above),
        )

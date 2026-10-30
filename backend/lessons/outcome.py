"""What a finished attempt's score leads to: its band, and the follow-up offer.

Apart from `attempts.py` so that the `grade_test` graph (a legacy attempt with open-ended answers, graded later) can use
the same rule as `AttemptService.submit` without importing the service that starts runs.
"""

from dataclasses import dataclass
from typing import Protocol

from django.utils import timezone

from graph.scoring import ScoreBand, Thresholds

from .models import Lesson, TestSubmission


@dataclass(frozen=True)
class AttemptFacts:
    """What an offer may depend on: how the attempt went, and whether it counts."""

    attempt_no: int
    awarded: int
    available: int
    band: str
    all_blank: bool  # an empty attempt scores 0 but must not count toward the Foundation offer (decided in C24)


class FollowupHook(Protocol):
    def offer(self, lesson: Lesson, facts: AttemptFacts) -> dict | None:
        """The follow-up offer for this attempt, stored on it, or None."""
        ...


class NoFollowup:
    """The hook in this phase: no offers. `FollowupPolicy` (phase 9.4) replaces it without changing the callers."""

    def offer(self, lesson: Lesson, facts: AttemptFacts) -> dict | None:
        return None


@dataclass(frozen=True)
class Decision:
    band: str
    followup: dict | None


class AttemptOutcome:
    """What a finished score leads to: its band, and the follow-up offer. One rule with two callers: `submit` (a lesson
    attempt is graded in full there) and the `grade_test` graph (a legacy attempt with open-ended answers)."""

    DEFAULT_THRESHOLDS = Thresholds()

    def __init__(self, followups: FollowupHook | None = None):
        self.followups = followups or NoFollowup()

    def thresholds(self, lesson: Lesson) -> Thresholds:
        snapshot = lesson.settings_snapshot or {}
        return Thresholds(
            fail_below=snapshot.get("band_fail_below", self.DEFAULT_THRESHOLDS.fail_below),
            excellent_above=snapshot.get("band_excellent_above", self.DEFAULT_THRESHOLDS.excellent_above),
        )

    def decide(self, lesson: Lesson, attempt_no: int, card: dict, *, all_blank: bool) -> Decision:
        score = card["score"]
        if score["available"] <= 0:
            return Decision("", None)
        band = ScoreBand.of(score["awarded"], score["available"], self.thresholds(lesson)).value
        facts = AttemptFacts(attempt_no, score["awarded"], score["available"], band, all_blank)
        return Decision(band, self.followups.offer(lesson, facts))

    def graded(self, attempt: TestSubmission, card: dict) -> None:
        """A legacy attempt whose open-ended answers are now graded: its card is final, and so is what follows from it.
        Writes the result and what it implies, and nothing else."""
        decision = self.decide(attempt.lesson, attempt.attempt_no, card, all_blank=attempt.all_blank)
        score = card["score"]
        TestSubmission.objects.filter(pk=attempt.pk, status=TestSubmission.Status.GRADING).update(
            result=card,
            status=TestSubmission.Status.GRADED,
            error="",
            graded_at=timezone.now(),
            awarded=score["awarded"],
            available=score["available"],
            band=decision.band,
            followup=decision.followup,
        )

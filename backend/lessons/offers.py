"""Turning a finished attempt into a follow-up offer: the facts the pure rule needs, read from the database.

`graph.followups.FollowupPolicy` decides; this gathers what it decides on (who the learner is, whether they have passed
before, which follow-ups exist) and stores nothing itself: `AttemptOutcome` writes the offer on the attempt. It is a
separate module from `followups.py` (the service that makes the lesson) so the `grade_test` graph can use it without
importing the services, which import the runner, which imports the graphs.
"""

from graph.followups import FollowupPolicy, Passes
from graph.levels import Level, LevelScheme, RaterCategory, StarRating
from graph.scoring import ScoreBand, Thresholds

from .models import Lesson, TestSubmission


class RaterCategories:
    """How the learner placed themselves, which is what decides whether a result contradicts it."""

    @staticmethod
    def of(lesson: Lesson) -> RaterCategory:
        """From the stars when they rated themselves, else from the level the lesson was written for (read by the names
        its document was written under). A follow-up lesson's level is fixed by what it is for, so a Foundation
        follow-up is
        a low rater and an Advanced one a high rater, and the offers stop on their own. A lesson with no level yet is
        mid."""
        if lesson.self_rating_halves:
            return StarRating(lesson.self_rating_halves).rater_category()
        if lesson.assessment:
            return RaterCategory.of(LevelScheme.level_of(lesson.assessment))
        if lesson.level:
            return RaterCategory.of(Level.parse(lesson.level))
        return RaterCategory.MID


class PolicyFollowups:
    """The `FollowupHook` of `AttemptOutcome`: runs `FollowupPolicy` and returns the offer as JSON, or None."""

    def __init__(self, policy: FollowupPolicy | None = None):
        self.policy = policy or FollowupPolicy()

    def offer(self, lesson: Lesson, facts) -> dict | None:
        fail_below = (lesson.settings_snapshot or {}).get("band_fail_below", Thresholds().fail_below)
        earlier = TestSubmission.objects.filter(
            lesson=lesson, status=TestSubmission.Status.GRADED, attempt_no__lt=facts.attempt_no, available__gt=0
        ).values_list("awarded", "available")
        existing = {
            level: str(pk)
            for level, pk in lesson.followups.exclude(followup_level="")
            .order_by("created_at")
            .values_list("followup_level", "pk")
        }
        offer = self.policy.decide(
            ScoreBand(facts.band),
            RaterCategories.of(lesson),
            Passes.once(earlier, fail_below),
            existing,
            blank=facts.all_blank,
        )
        return offer.to_json() if offer else None

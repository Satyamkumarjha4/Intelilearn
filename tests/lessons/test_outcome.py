"""Unit under test: `lessons.outcome.AttemptOutcome`, the one rule for what a finished attempt's score leads to (T10).

Why: a lesson attempt is graded at submit, and a legacy attempt with open-ended answers is graded later by the
`grade_test` graph. Both must reach the same band and the same offer, so they call one class. The offer itself is built
in `lessons/offers.py` (phase 9.4) behind a seam (`FollowupHook`), and this file pins the seam: any hook plugs in
without
touching the callers.

Use cases:
- the band comes from whole marks and the lesson's own thresholds (default 30 and 90 percent): the edges are Normal,
  29 is Fail, 91 is Excellent, and a total where 90 percent is not a whole number of marks is judged exactly
- a lesson made before the settings existed uses the defaults
- no marks available gives no band and no offer
- the follow-up hook is asked once with the attempt number, marks, band and whether every answer was blank, and what it
  returns is the offer; the default hook is the follow-up policy (its cases are in test_offers.py)
- grading a legacy attempt later writes the result, the marks, the band and the offer, only while it is being graded
"""

import pytest

from lessons.models import TestSubmission
from lessons.offers import PolicyFollowups
from lessons.outcome import AttemptFacts, AttemptOutcome

pytestmark = pytest.mark.django_db


def card(awarded, available):
    return {"complete": True, "score": {"awarded": awarded, "available": available, "percent": 0}, "questions": []}


class RecordingHook:
    def __init__(self, offer=None):
        self.calls = []
        self._offer = offer

    def offer(self, lesson, facts):
        self.calls.append((lesson.pk, facts))
        return self._offer


class TestBand:
    @pytest.mark.parametrize(
        ("awarded", "available", "band"),
        [(5, 20, "fail"), (6, 20, "normal"), (18, 20, "normal"), (19, 20, "excellent"), (20, 20, "excellent"),
         (0, 20, "fail"), (29, 100, "fail"), (30, 100, "normal"), (90, 100, "normal"), (91, 100, "excellent"),
         (17, 18, "excellent"), (16, 18, "normal"), (15, 18, "normal"), (5, 18, "fail"), (6, 18, "normal")],
    )  # fmt: skip
    def test_the_band_is_decided_on_whole_marks(self, lesson, awarded, available, band):
        decision = AttemptOutcome().decide(lesson, 1, card(awarded, available), all_blank=False)

        assert decision.band == band

    def test_the_lessons_own_thresholds_are_used(self, make_lesson):
        lesson = make_lesson(settings_snapshot={"band_fail_below": 50, "band_excellent_above": 80})

        assert AttemptOutcome().decide(lesson, 1, card(9, 20), all_blank=False).band == "fail"
        assert AttemptOutcome().decide(lesson, 1, card(17, 20), all_blank=False).band == "excellent"

    def test_a_lesson_made_before_the_settings_existed_uses_the_defaults(self, make_lesson):
        lesson = make_lesson(settings_snapshot={"max_interactives_per_page": 3})

        assert AttemptOutcome().decide(lesson, 1, card(5, 20), all_blank=False).band == "fail"
        assert AttemptOutcome().decide(lesson, 1, card(6, 20), all_blank=False).band == "normal"

    def test_no_marks_available_is_no_band_and_no_offer(self, lesson):
        hook = RecordingHook({"kind": "x"})

        decision = AttemptOutcome(hook).decide(lesson, 1, card(0, 0), all_blank=False)

        assert (decision.band, decision.followup) == ("", None) and hook.calls == []


class TestTheFollowupSeam:
    def test_the_default_hook_is_the_follow_up_policy(self, lesson):
        assert isinstance(AttemptOutcome().followups, PolicyFollowups)

    def test_the_default_hook_offers_a_foundation_lesson_to_a_learner_who_failed_and_nothing_to_one_who_passed(
        self, lesson
    ):
        failed = AttemptOutcome().decide(lesson, 1, card(2, 20), all_blank=False)
        passed = AttemptOutcome().decide(lesson, 1, card(12, 20), all_blank=False)

        assert failed.followup == {"kind": "foundation", "action": "generate", "lesson_id": None}
        assert passed.followup is None

    def test_a_hook_is_asked_once_with_the_facts_and_its_offer_is_the_followup(self, lesson):
        hook = RecordingHook({"kind": "foundation", "action": "generate", "lesson_id": None})

        decision = AttemptOutcome(hook).decide(lesson, 3, card(4, 20), all_blank=False)

        assert decision.followup == {"kind": "foundation", "action": "generate", "lesson_id": None}
        assert hook.calls == [(lesson.pk, AttemptFacts(3, 4, 20, "fail", False))]

    def test_an_attempt_of_blank_answers_reaches_the_hook_flagged_so_it_can_be_left_out(self, lesson):
        hook = RecordingHook()

        AttemptOutcome(hook).decide(lesson, 1, card(0, 20), all_blank=True)

        assert hook.calls[0][1].all_blank is True and hook.calls[0][1].band == "fail"


class TestGradedLater:
    def waiting(self, lesson, status="grading", **fields):
        return TestSubmission.objects.create(lesson=lesson, status=status, **fields)

    def test_the_finished_card_band_and_offer_are_written_and_nothing_else(self, lesson):
        attempt = self.waiting(lesson, answers={"t1": 1}, questions=[{"id": "t1"}], all_blank=False)
        hook = RecordingHook({"kind": "foundation"})

        AttemptOutcome(hook).graded(attempt, card(5, 6))

        attempt.refresh_from_db()
        assert attempt.status == "graded" and attempt.result["score"]["awarded"] == 5
        assert (attempt.awarded, attempt.available, attempt.band, attempt.followup) == (
            5,
            6,
            "normal",
            {"kind": "foundation"},
        )
        assert attempt.graded_at is not None and attempt.answers == {"t1": 1} and attempt.questions == [{"id": "t1"}]
        assert hook.calls[0][1] == AttemptFacts(1, 5, 6, "normal", False)

    @pytest.mark.parametrize("status", ["graded", "failed", "in_progress", "generating"])
    def test_an_attempt_that_is_not_being_graded_is_left_alone(self, lesson, status):
        attempt = self.waiting(lesson, status=status)

        AttemptOutcome().graded(attempt, card(5, 6))

        attempt.refresh_from_db()
        assert attempt.status == status and attempt.result is None and attempt.band == ""

"""Unit under test: `lessons.offers`: `RaterCategories` (how the learner placed themselves) and `PolicyFollowups` (the
hook that gives `AttemptOutcome` its follow-up offer), with the rule itself in `graph.followups`.

Why: the rule is pure and table-tested, but it is only right if it is given the right facts: who the learner is (from
their stars, or from the level their lesson was written for), whether an *earlier* attempt passed (the current one does
not count), and which follow-ups already exist. A wrong fact here hands out a second Foundation lesson, or hides the
first one, or tells a mid rater who has passed to start from the basics.

Use cases:
- a self-rated lesson's category comes from its stars; any other lesson's from the level of its assessment, read by the
  names it was written under (an old "beginner" meant Foundation, so mid); the Expert lesson chosen after a perfect
  quick check is high; a lesson with no level yet is mid
- a follow-up lesson's category comes from its level: a Foundation follow-up is Beginner and so low, an Advanced one is
  Expert and so high
- the hook counts only the graded attempts before the current one, judged on the lesson's own Fail line, and not a
  retake in progress or an attempt still being graded
- the hook finds the follow-ups the lesson already has, by level, and offers to revisit or open them
- an attempt of blank answers gets no offer
- the spec's worked examples, played through the real outcome rule on real attempts in the database
- the same offer is stored whether the attempt is graded at submit or later (the legacy path)
"""

import pytest

from graph.levels import LevelScheme, RaterCategory
from lessons.models import Lesson, TestSubmission
from lessons.offers import PolicyFollowups, RaterCategories
from lessons.outcome import AttemptFacts, AttemptOutcome

pytestmark = pytest.mark.django_db


def card(awarded, available=20):
    return {"complete": True, "score": {"awarded": awarded, "available": available, "percent": 0}, "questions": []}


def assessment(level, scheme=True):
    document = {"level": level, "known_concepts": [], "gaps": [], "start_point": "", "confidence": "low"}
    return LevelScheme.stamp(document) if scheme else document


class TestRaterCategories:
    @pytest.mark.parametrize(("halves", "category"), [
        (1, RaterCategory.LOW), (3, RaterCategory.LOW), (4, RaterCategory.MID), (7, RaterCategory.MID),
        (8, RaterCategory.MID), (9, RaterCategory.HIGH), (10, RaterCategory.HIGH),
    ])  # fmt: skip
    def test_a_self_rated_lesson_is_placed_by_its_stars(self, make_lesson, halves, category):
        lesson = make_lesson(entry="self_rating", self_rating_halves=halves, assessment=assessment("foundation"))

        assert RaterCategories.of(lesson) is category

    @pytest.mark.parametrize(("level", "category"), [
        ("beginner", RaterCategory.LOW), ("foundation", RaterCategory.MID), ("proficient", RaterCategory.MID),
        ("expert", RaterCategory.HIGH),
    ])  # fmt: skip
    def test_a_lesson_from_the_quick_check_is_placed_by_the_level_of_its_assessment(self, make_lesson, level, category):
        assert RaterCategories.of(make_lesson(assessment=assessment(level))) is category

    def test_an_assessment_from_before_the_rename_is_read_by_the_old_names(self, make_lesson):
        old = make_lesson(assessment=assessment("beginner", scheme=False))  # then it meant Foundation
        oldest = make_lesson(assessment=assessment("novice", scheme=False))

        assert RaterCategories.of(old) is RaterCategory.MID
        assert RaterCategories.of(oldest) is RaterCategory.LOW

    def test_the_expert_lesson_chosen_after_a_perfect_quick_check_is_high(self, make_lesson):
        lesson = make_lesson(route="lesson", level="expert", assessment=assessment("expert"))

        assert RaterCategories.of(lesson) is RaterCategory.HIGH

    def test_a_lesson_with_only_a_level_uses_it_and_one_with_nothing_is_mid(self, make_lesson):
        assert RaterCategories.of(make_lesson(level="beginner")) is RaterCategory.LOW
        assert RaterCategories.of(make_lesson()) is RaterCategory.MID

    @pytest.mark.parametrize(
        ("followup", "level", "category"),
        [
            ("foundation", "beginner", RaterCategory.LOW),
            ("advanced", "expert", RaterCategory.HIGH),
        ],
    )
    def test_a_followup_lessons_category_comes_from_its_level_so_chains_stop_on_their_own(
        self, make_lesson, lesson, followup, level, category
    ):
        child = make_lesson(
            entry="followup", origin="followup", created_from_lesson=lesson, followup_level=followup, level=level,
            assessment=assessment(level),
        )  # fmt: skip

        assert RaterCategories.of(child) is category


def attempt(lesson, number, awarded, available=20, status="graded"):
    return TestSubmission.objects.create(
        lesson=lesson, attempt_no=number, status=status, awarded=awarded, available=available, band="x"
    )


class TestPolicyFollowups:
    def facts(self, number, awarded=2, available=20, band="fail", blank=False):
        return AttemptFacts(number, awarded, available, band, blank)

    def test_only_earlier_graded_attempts_count_towards_having_passed(self, lesson):
        attempt(lesson, 1, 2)
        attempt(lesson, 2, 15, status="in_progress")  # not graded
        attempt(lesson, 3, 15, status="grading")
        attempt(lesson, 5, 15)  # later than the one being judged

        offer = PolicyFollowups().offer(lesson, self.facts(4))

        assert offer == {"kind": "foundation", "action": "generate", "lesson_id": None}

    def test_an_earlier_pass_ends_the_foundation_offers(self, lesson):
        attempt(lesson, 1, 6)  # exactly 30%

        assert PolicyFollowups().offer(lesson, self.facts(2)) is None

    def test_the_current_attempt_never_counts_as_the_pass(self, lesson):
        attempt(lesson, 1, 12)  # the row being decided is already stored, at its own number

        assert PolicyFollowups().offer(lesson, self.facts(1, awarded=2)) == {
            "kind": "foundation", "action": "generate", "lesson_id": None,
        }  # fmt: skip

    def test_the_lessons_own_fail_line_decides_what_a_pass_is(self, make_lesson):
        lesson = make_lesson(settings_snapshot={"band_fail_below": 50})
        attempt(lesson, 1, 8)  # 40%: a pass at the default line, a fail at 50

        assert PolicyFollowups().offer(lesson, self.facts(2))["kind"] == "foundation"

    def test_an_existing_foundation_lesson_is_revisited_and_an_advanced_one_opened(self, lesson, make_lesson):
        foundation = make_lesson(created_from_lesson=lesson, followup_level="foundation")
        advanced = make_lesson(created_from_lesson=lesson, followup_level="advanced")

        revisit = PolicyFollowups().offer(lesson, self.facts(1))
        open_ = PolicyFollowups().offer(lesson, self.facts(2, awarded=19, band="excellent"))

        assert revisit == {"kind": "foundation", "action": "revisit", "lesson_id": str(foundation.pk)}
        assert open_ == {"kind": "advanced", "action": "open", "lesson_id": str(advanced.pk)}

    def test_another_learners_lessons_are_not_this_lessons_followups(self, lesson, make_lesson, other_user):
        make_lesson(owner=other_user, topic="Unrelated", followup_level="foundation")

        assert PolicyFollowups().offer(lesson, self.facts(1))["action"] == "generate"

    def test_an_attempt_of_blank_answers_gets_no_offer(self, lesson):
        assert PolicyFollowups().offer(lesson, self.facts(1, awarded=0, blank=True)) is None

    def test_a_low_rater_who_fails_gets_the_inline_suggestion(self, make_lesson):
        lesson = make_lesson(entry="self_rating", self_rating_halves=2)

        assert PolicyFollowups().offer(lesson, self.facts(1)) == {
            "kind": "inline_suggestion", "action": "revisit_or_related", "lesson_id": None,
        }  # fmt: skip


class TestTheWorkedExamplesOnRealAttempts:
    """Spec 3.3, through `AttemptOutcome` on rows in the database: each attempt is stored before the next is judged, and
    the learner makes the lesson they are offered."""

    def play(self, lesson, percents):
        offers = []
        for number, percent in enumerate(percents, start=1):
            decision = AttemptOutcome().decide(lesson, number, card(percent, 100), all_blank=False)
            offers.append(
                None if decision.followup is None else f"{decision.followup['kind']}:{decision.followup['action']}"
            )
            attempt(lesson, number, percent, 100)
            if decision.followup and decision.followup["action"] == "generate":
                Lesson.objects.create(
                    owner=lesson.owner, topic=f"{decision.followup['kind']} {lesson.pk}", created_from_lesson=lesson,
                    followup_level=decision.followup["kind"],
                )  # fmt: skip
        return offers

    def test_mid_fail_fail_pass_fail_excellent(self, make_lesson):
        lesson = make_lesson(entry="self_rating", self_rating_halves=6)

        assert self.play(lesson, [10, 10, 50, 10, 95]) == [
            "foundation:generate", "foundation:revisit", None, None, "advanced:generate"
        ]  # fmt: skip

    def test_mid_normal_fail_excellent(self, make_lesson):
        lesson = make_lesson(entry="self_rating", self_rating_halves=6)

        assert self.play(lesson, [50, 10, 95]) == [None, None, "advanced:generate"]

    def test_low_fail_fail(self, make_lesson):
        lesson = make_lesson(entry="self_rating", self_rating_halves=2)

        assert self.play(lesson, [10, 10]) == ["inline_suggestion:revisit_or_related"] * 2

    def test_low_excellent(self, make_lesson):
        assert self.play(make_lesson(entry="self_rating", self_rating_halves=2), [95]) == ["advanced:generate"]

    def test_high_excellent(self, make_lesson):
        assert self.play(make_lesson(entry="self_rating", self_rating_halves=10), [95]) == [None]

    def test_high_4_5_fail(self, make_lesson):
        assert self.play(make_lesson(entry="self_rating", self_rating_halves=9), [10]) == ["foundation:generate"]

    def test_a_second_excellent_opens_the_advanced_lesson_made_after_the_first(self, make_lesson):
        lesson = make_lesson(entry="self_rating", self_rating_halves=6)

        assert self.play(lesson, [95, 96]) == ["advanced:generate", "advanced:open"]


class TestGradedLaterStoresTheSameOffer:
    def test_a_legacy_attempt_graded_by_the_run_gets_its_offer(self, lesson):
        waiting = TestSubmission.objects.create(lesson=lesson, attempt_no=1, status="grading", all_blank=False)

        AttemptOutcome().graded(waiting, card(2, 20))

        waiting.refresh_from_db()
        assert waiting.status == "graded" and waiting.followup == {
            "kind": "foundation",
            "action": "generate",
            "lesson_id": None,
        }

    def test_a_blank_legacy_attempt_gets_none(self, lesson):
        waiting = TestSubmission.objects.create(lesson=lesson, attempt_no=1, status="grading", all_blank=True)

        AttemptOutcome().graded(waiting, card(0, 20))

        waiting.refresh_from_db()
        assert waiting.followup is None

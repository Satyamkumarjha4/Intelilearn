"""Unit under test: `graph.followups`: `FollowupPolicy` (what a finished attempt leads to), `Offer`, and `Passes`
(whether a learner has already passed).

Why: this is the rule that decides whether a learner is told "you may want to start from the basics" or "ready for
more".
The spec's own words are that Socra must not tell people they are wrong about their own level, and that a low rater who
fails rated themselves correctly. Getting a case wrong either insults a learner or hands out lessons that cost money, so
the spec's pseudocode and all six of its worked examples are the fixture table here.

Use cases:
- the six worked examples of spec section 3.3, played attempt by attempt (the learner generates the lesson offered, so
  the
  next offer finds it)
- a Fail: a low rater gets only the inline suggestion; anyone else gets the Foundation offer until they have passed
  once,
  and never again after; the offer is to generate it, or to revisit it when it exists (with its id)
- an Excellent: a high rater gets nothing; anyone else gets the Advanced offer on every such attempt, to generate it
  or to
  open it when it exists (with its id)
- the cross cases always get an offer: a low rater who excels, a high rater who fails
- a Normal attempt never gets an offer, whoever rated
- an attempt of blank answers never gets an offer, even a Fail by a mid rater who has never passed (it must not farm a
  Foundation lesson), and does not count as a pass
- the Foundation lesson existing does not change the Advanced offer and the reverse
- passing means a score at or above the Fail line, judged on whole marks, so exactly 30% is a pass and one mark less
  is not
- an offer is stored as plain JSON and read back the same
- a Foundation follow-up is written for a Beginner and an Advanced one for an Expert, which makes them a low and a
  high rater
  so chains of follow-ups stop on their own; any other level is refused
- only a Fail, a Normal or an Excellent band is understood
"""

import pytest

from graph.followups import FollowupPolicy, FollowupTargets, Offer, Passes
from graph.levels import Level, RaterCategory, StarRating
from graph.scoring import ScoreBand

LOW, MID, HIGH = RaterCategory.LOW, RaterCategory.MID, RaterCategory.HIGH
FAIL, NORMAL, EXCELLENT = ScoreBand.FAIL, ScoreBand.NORMAL, ScoreBand.EXCELLENT
POLICY = FollowupPolicy()


def label(offer: Offer | None) -> str:
    if offer is None:
        return "none"
    return "inline suggestion" if offer.kind == "inline_suggestion" else f"{offer.kind} ({offer.action})"


def play(stars: float, percents: list[int]) -> list[str]:
    """The offers a learner gets over a run of attempts, generating each lesson they are offered."""
    rater = StarRating.from_stars(stars).rater_category()
    existing: dict[str, str] = {}
    scores: list[tuple[int, int]] = []
    offers = []
    for percent in percents:
        band = ScoreBand.of(percent, 100)
        offer = POLICY.decide(band, rater, Passes.once(scores), existing)
        offers.append(label(offer))
        if offer and offer.action == "generate":
            existing[offer.kind] = f"{offer.kind}-lesson"
        scores.append((percent, 100))
    return offers


# (rating in stars, the score of each attempt in percent, the offer after each)
WORKED_EXAMPLES = [
    (3, [10, 10, 50, 10, 95], ["foundation (generate)", "foundation (revisit)", "none", "none", "advanced (generate)"]),
    (3, [50, 10, 95], ["none", "none", "advanced (generate)"]),
    (1, [10, 10], ["inline suggestion", "inline suggestion"]),
    (1, [95], ["advanced (generate)"]),
    (5, [95], ["none"]),
    (4.5, [10], ["foundation (generate)"]),
]


@pytest.mark.parametrize(("stars", "percents", "offers"), WORKED_EXAMPLES, ids=[
    "mid: fail, fail, pass, fail, excellent", "mid: normal, fail, excellent", "low: fail, fail", "low: excellent",
    "high: excellent", "high 4.5: fail",
])  # fmt: skip
def test_the_worked_examples_of_the_spec(stars, percents, offers):
    assert play(stars, percents) == offers


class TestFail:
    @pytest.mark.parametrize("passed", [False, True])
    def test_a_low_rater_who_fails_gets_only_the_inline_suggestion(self, passed):
        offer = POLICY.decide(FAIL, LOW, passed, {})

        assert offer == Offer("inline_suggestion", "revisit_or_related")

    @pytest.mark.parametrize("rater", [MID, HIGH])
    def test_anyone_else_is_offered_a_foundation_lesson_until_they_have_passed_once(self, rater):
        assert POLICY.decide(FAIL, rater, False, {}) == Offer("foundation", "generate")

    @pytest.mark.parametrize("rater", [MID, HIGH])
    def test_after_a_pass_a_fail_gets_nothing(self, rater):
        assert POLICY.decide(FAIL, rater, True, {}) is None
        assert POLICY.decide(FAIL, rater, True, {"foundation": "f1"}) is None

    def test_an_existing_foundation_lesson_is_revisited_not_made_again(self):
        offer = POLICY.decide(FAIL, MID, False, {"foundation": "f1"})

        assert offer == Offer("foundation", "revisit", "f1")

    def test_an_advanced_lesson_does_not_stand_in_for_a_foundation_one(self):
        assert POLICY.decide(FAIL, MID, False, {"advanced": "a1"}) == Offer("foundation", "generate")


class TestExcellent:
    @pytest.mark.parametrize("passed", [False, True])
    def test_a_high_rater_who_excels_gets_nothing(self, passed):
        assert POLICY.decide(EXCELLENT, HIGH, passed, {}) is None

    @pytest.mark.parametrize("rater", [LOW, MID])
    @pytest.mark.parametrize("passed", [False, True])
    def test_anyone_else_is_offered_an_advanced_lesson_on_every_such_attempt(self, rater, passed):
        assert POLICY.decide(EXCELLENT, rater, passed, {}) == Offer("advanced", "generate")

    @pytest.mark.parametrize("rater", [LOW, MID])
    def test_an_existing_advanced_lesson_is_opened_not_made_again(self, rater):
        assert POLICY.decide(EXCELLENT, rater, True, {"advanced": "a1"}) == Offer("advanced", "open", "a1")

    def test_a_foundation_lesson_does_not_stand_in_for_an_advanced_one(self):
        assert POLICY.decide(EXCELLENT, MID, False, {"foundation": "f1"}) == Offer("advanced", "generate")


class TestNormalAndBlank:
    @pytest.mark.parametrize("rater", [LOW, MID, HIGH])
    @pytest.mark.parametrize("passed", [False, True])
    def test_a_normal_attempt_never_gets_an_offer(self, rater, passed):
        assert POLICY.decide(NORMAL, rater, passed, {"foundation": "f1", "advanced": "a1"}) is None

    @pytest.mark.parametrize("rater", [LOW, MID, HIGH])
    def test_an_attempt_of_blank_answers_never_gets_an_offer(self, rater):
        assert POLICY.decide(FAIL, rater, False, {}, blank=True) is None

    def test_a_run_of_blank_attempts_does_not_farm_a_foundation_lesson(self):
        # the empty submit scores 0, a Fail, and the learner has never passed
        offers = [POLICY.decide(FAIL, MID, Passes.once([(0, 20)] * n), {}, blank=True) for n in range(4)]

        assert offers == [None] * 4

    def test_an_unknown_band_is_refused(self):
        with pytest.raises(ValueError, match="band"):
            POLICY.decide("great", MID, False, {})


class TestPasses:
    @pytest.mark.parametrize(("awarded", "available", "passed"), [
        (6, 20, True),  # exactly 30%
        (5, 20, False),  # 25%
        (3, 10, True), (29, 100, False), (30, 100, True), (0, 20, False), (20, 20, True),
    ])  # fmt: skip
    def test_a_score_at_or_above_the_fail_line_is_a_pass(self, awarded, available, passed):
        assert Passes.once([(awarded, available)]) is passed

    def test_one_pass_among_fails_is_enough(self):
        assert Passes.once([(0, 20), (1, 20), (7, 20), (0, 20)]) is True

    def test_no_attempts_is_no_pass(self):
        assert Passes.once([]) is False

    def test_the_line_comes_from_the_lessons_settings(self):
        assert Passes.once([(8, 20)], fail_below=50) is False
        assert Passes.once([(10, 20)], fail_below=50) is True

    def test_an_attempt_with_nothing_available_is_not_a_pass(self):
        assert Passes.once([(0, 0)]) is False


class TestOffer:
    @pytest.mark.parametrize("offer", [
        Offer("foundation", "generate"), Offer("foundation", "revisit", "f1"), Offer("advanced", "open", "a1"),
        Offer("inline_suggestion", "revisit_or_related"),
    ])  # fmt: skip
    def test_it_is_stored_as_plain_json_and_read_back_the_same(self, offer):
        assert Offer.from_json(offer.to_json()) == offer
        assert set(offer.to_json()) == {"kind", "action", "lesson_id"}

    def test_a_lesson_id_is_stored_as_text(self):
        import uuid

        lesson_id = uuid.uuid4()

        assert Offer("advanced", "open", lesson_id).to_json()["lesson_id"] == str(lesson_id)


class TestFollowupTargets:
    @pytest.mark.parametrize(("followup", "level"), [("foundation", Level.BEGINNER), ("advanced", Level.EXPERT)])
    def test_each_followup_is_written_for_its_level(self, followup, level):
        assert FollowupTargets.level_for(followup) is level

    @pytest.mark.parametrize(("followup", "rater"), [("foundation", LOW), ("advanced", HIGH)])
    def test_chains_stop_on_their_own(self, followup, rater):
        """A Beginner who fails is told to revisit and an Expert who excels is told nothing."""
        assert RaterCategory.of(FollowupTargets.level_for(followup)) is rater
        beginner_fails = POLICY.decide(FAIL, LOW, False, {})
        expert_excels = POLICY.decide(EXCELLENT, HIGH, False, {})

        assert beginner_fails.kind == "inline_suggestion" and expert_excels is None

    @pytest.mark.parametrize("followup", ["", "intermediate", None, "Foundation"])
    def test_any_other_level_is_refused(self, followup):
        with pytest.raises(ValueError, match="follow-up level"):
            FollowupTargets.level_for(followup)

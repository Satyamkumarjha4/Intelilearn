"""Unit under test: `graph.ladder.AdaptiveLadder`: the five-question calibration walk that finds a level (plan §9.4,
R16).

Why: the calibration quiz asks one multiple-choice question at a time, harder after a right answer and easier after a
wrong one, and its result becomes the level of a whole quiz. The questions are written once (a pool of two for each of
the diagnostic's five bands) and the ladder only picks, so there is no model call between questions. The level is a
table of where the learner ended up and how many they got right; every one of the 32 ways to answer five questions must
land on a level, and a better run must never give a lower one.

Use cases:
- the walk starts at the middle band (standard)
- a right answer moves one band up, a wrong one moves one down, and the ends hold
- the walk is five questions long (a setting makes it 3 to 7, scaled onto the table), and its level is only known after
  the last answer
- the level is read from a table of (band reached, number right); the table is the one in the plan
- every one of the 32 ways to answer five questions has a level, and the table never gives a lower level for a better
  run (more right at the same band, or a higher band with the same number right)
- the next question is the first one of the band not asked yet; a band that is used up (an up-and-down walk asks the
  middle band three times, and the pool has two of each) falls back to the nearest band, the easier one on a tie, and
  no question is ever asked twice
- the band a question was asked at maps to a difficulty (standard for the start)
"""

from itertools import product

import pytest
from support.quiz_data import make_questions

from graph.ladder import AdaptiveLadder
from graph.levels import Difficulty, Level
from graph.schemas.diagnostic import BANDS

B, F, P, E = Level.BEGINNER, Level.FOUNDATION, Level.PROFICIENT, Level.EXPERT

# rows: the band reached (basic … hard); columns: the number right (0 … 5)
TABLE = (
    (B, B, B, F, F, F),
    (B, B, F, F, F, P),
    (B, F, F, F, P, P),
    (F, F, F, P, P, E),
    (F, F, P, P, E, E),
)


def walk(*answers: bool) -> list[bool]:
    return list(answers)


class TestTheWalk:
    def test_it_starts_at_the_middle_band(self):
        ladder = AdaptiveLadder()

        assert ladder.position([]) == 2 and BANDS[ladder.position([])] == "moderate"

    def test_a_right_answer_moves_up_and_a_wrong_one_down(self):
        ladder = AdaptiveLadder()

        assert ladder.position(walk(True)) == 3
        assert ladder.position(walk(False)) == 1
        assert ladder.position(walk(True, False)) == 2

    def test_the_top_and_the_bottom_hold(self):
        ladder = AdaptiveLadder()

        assert ladder.position(walk(True, True, True, True)) == 4
        assert ladder.position(walk(False, False, False, False)) == 0

    def test_it_is_five_questions_long(self):
        ladder = AdaptiveLadder()

        assert not ladder.done(walk(True, True, True, True))
        assert ladder.done(walk(True, True, True, True, True))
        assert ladder.QUESTIONS == 5

    def test_the_level_is_not_known_before_the_fifth_answer(self):
        with pytest.raises(ValueError, match="all 5 questions"):
            AdaptiveLadder().level(walk(True, True))

    def test_a_longer_walk_than_it_has_questions_is_refused(self):
        with pytest.raises(ValueError, match="5 questions long"):
            AdaptiveLadder().position(walk(*[True] * 6))


class TestTheLevel:
    @pytest.mark.parametrize("answers", list(product([False, True], repeat=5)))
    def test_every_way_to_answer_five_questions_has_the_level_the_table_gives(self, answers):
        ladder = AdaptiveLadder()
        band, right = ladder.position(list(answers)), sum(answers)

        assert ladder.level(list(answers)) is TABLE[band][right]

    def test_the_table_in_the_code_is_the_one_in_the_plan(self):
        for band, row in enumerate(TABLE):
            for right, level in enumerate(row):
                assert AdaptiveLadder.LEVELS[band][right] is level

    def test_all_wrong_is_a_beginner_and_all_right_is_an_expert(self):
        ladder = AdaptiveLadder()

        assert ladder.level(walk(*[False] * 5)) is Level.BEGINNER
        assert ladder.level(walk(*[True] * 5)) is Level.EXPERT

    def test_a_miss_at_the_top_after_four_right_is_proficient_not_expert(self):
        assert AdaptiveLadder().level(walk(True, True, True, True, False)) is Level.PROFICIENT

    def test_going_up_and_down_around_the_middle_is_foundation_or_proficient_by_the_count(self):
        ladder = AdaptiveLadder()

        assert ladder.level(walk(False, True, False, True, False)) is Level.FOUNDATION  # 2 right, band 1
        assert ladder.level(walk(True, False, True, False, True)) is Level.PROFICIENT  # 3 right, band 3

    def test_a_better_run_never_gives_a_lower_level(self):
        order = list(Level)
        for band in range(len(TABLE)):
            for right in range(5):
                assert order.index(TABLE[band][right]) <= order.index(TABLE[band][right + 1])
        for right in range(6):
            for band in range(len(TABLE) - 1):
                assert order.index(TABLE[band][right]) <= order.index(TABLE[band + 1][right])


class TestOtherLengths:
    @pytest.mark.parametrize("questions", [3, 4, 5, 6, 7])
    def test_all_right_is_an_expert_and_all_wrong_a_beginner_at_every_length(self, questions):
        ladder = AdaptiveLadder(questions)

        assert ladder.level(walk(*[True] * questions)) is Level.EXPERT
        assert ladder.level(walk(*[False] * questions)) is Level.BEGINNER

    @pytest.mark.parametrize(
        ("questions", "right", "scaled"), [(3, 0, 0), (3, 1, 2), (3, 2, 3), (3, 3, 5), (7, 4, 3), (7, 7, 5), (5, 4, 4)]
    )
    def test_the_number_right_is_scaled_onto_the_table(self, questions, right, scaled):
        assert AdaptiveLadder(questions).scaled(right) == scaled

    def test_the_walk_ends_after_its_own_length(self):
        ladder = AdaptiveLadder(3)

        assert not ladder.done(walk(True, True)) and ladder.done(walk(True, True, True))
        with pytest.raises(ValueError, match="3 questions long"):
            ladder.position(walk(*[True] * 4))

    @pytest.mark.parametrize("questions", [2, 8, 5.0, "5", None, True])
    def test_a_length_outside_three_to_seven_is_refused(self, questions):
        with pytest.raises(ValueError, match="3 to 7"):
            AdaptiveLadder(questions)


class TestPickingTheQuestion:
    POOL = make_questions()  # q1 … q10, two for each band, easiest first

    def test_the_first_question_is_the_first_of_the_middle_band(self):
        question = AdaptiveLadder().pick(self.POOL, [], [])

        assert (question["id"], question["band"]) == ("q5", "moderate")

    def test_a_right_answer_asks_the_next_band_up(self):
        question = AdaptiveLadder().pick(self.POOL, ["q5"], walk(True))

        assert question["band"] == "moderate_hard"

    def test_a_question_already_asked_is_not_asked_again(self):
        question = AdaptiveLadder().pick(self.POOL, ["q5", "q7"], walk(True, False))

        assert (question["id"], question["band"]) == ("q6", "moderate")

    def test_an_up_and_down_walk_asks_the_middle_band_a_third_time_from_the_nearest_band_with_questions_left(self):
        # the middle band's two questions are gone, and so are the two below it: the next band up is the nearest
        question = AdaptiveLadder().pick(self.POOL, ["q5", "q3", "q6", "q4"], walk(False, True, False, True))

        assert question["band"] == "moderate_hard"

    def test_a_band_that_is_used_up_falls_back_to_the_easier_neighbour_on_a_tie(self):
        question = AdaptiveLadder().pick(self.POOL, ["q5", "q6"], walk(True, False))

        assert question["band"] == "easy_moderate"  # as near as moderate_hard, and easier

    @pytest.mark.parametrize("answers", list(product([False, True], repeat=4)))
    def test_no_question_is_ever_asked_twice_and_one_is_always_found(self, answers):
        ladder, asked, given = AdaptiveLadder(), [], []
        for answer in (*answers, True):
            question = ladder.pick(self.POOL, asked, given)
            assert question["id"] not in asked
            asked.append(question["id"])
            given.append(answer)

        assert len(set(asked)) == 5

    def test_a_pool_with_no_unused_question_is_refused(self):
        everything = [q["id"] for q in self.POOL]

        with pytest.raises(ValueError, match="pool"):
            AdaptiveLadder().pick(self.POOL, everything, walk(True))


class TestBandsAndDifficulties:
    @pytest.mark.parametrize(
        ("position", "difficulty"),
        [(0, Difficulty.EASY), (1, Difficulty.BASIC), (2, Difficulty.STANDARD), (3, Difficulty.DIFFICULT),
         (4, Difficulty.EXPERT)],
    )  # fmt: skip
    def test_each_band_has_one_difficulty(self, position, difficulty):
        assert AdaptiveLadder.difficulty_of(position) is difficulty

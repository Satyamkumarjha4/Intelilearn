"""Unit under test: `graph.difficulty_mix.DifficultyMix`: how many questions of each difficulty a quick quiz asks, for a
learner's level and a question count (plan D21).

Why: the shares are percentages, a quiz has 5 to 30 questions, and a count that does not divide evenly has to land
somewhere. Largest-remainder rounding makes every preset add up exactly, and a tie goes to the easier difficulty, so a
rounding choice never makes a quiz harder than the table says. A share of zero must stay zero (a Beginner is never asked
an expert question because of rounding).

Use cases:
- the shares of every level add up to 100
- for every level and every preset (5, 10, 15, 20, 25, 30) the counts add up to the count asked for
- a difficulty with a zero share gets no questions, whatever the count
- the counts at 10 questions are the table's percentages
- when a count does not divide evenly the largest remainder wins, and a tie goes to the easier difficulty
- the difficulties of a mix are listed easiest first, as many times as each was asked for
- a level is read in any case; a negative or fractional count, or an unknown level, is refused
"""

import pytest

from graph.difficulty_mix import DifficultyMix
from graph.levels import Difficulty, Level

PRESETS = (5, 10, 15, 20, 25, 30)
ORDER = (Difficulty.EASY, Difficulty.BASIC, Difficulty.STANDARD, Difficulty.DIFFICULT, Difficulty.EXPERT)


def counts(level, count):
    mix = DifficultyMix.for_level(level, count)
    return tuple(mix.counts[d] for d in ORDER)


class TestTheTable:
    @pytest.mark.parametrize("level", list(Level))
    def test_the_shares_of_a_level_add_up_to_a_hundred(self, level):
        assert sum(DifficultyMix.SHARES[level].values()) == 100

    @pytest.mark.parametrize("level", list(Level))
    def test_every_difficulty_has_a_share(self, level):
        assert set(DifficultyMix.SHARES[level]) == set(ORDER)


class TestEveryPreset:
    @pytest.mark.parametrize("count", PRESETS)
    @pytest.mark.parametrize("level", list(Level))
    def test_the_counts_add_up_to_the_count_asked_for(self, level, count):
        assert sum(counts(level, count)) == count

    @pytest.mark.parametrize("count", PRESETS)
    @pytest.mark.parametrize("level", list(Level))
    def test_a_zero_share_stays_zero(self, level, count):
        mix = DifficultyMix.for_level(level, count)
        for difficulty, share in DifficultyMix.SHARES[level].items():
            if share == 0:
                assert mix.counts[difficulty] == 0

    @pytest.mark.parametrize("count", PRESETS)
    @pytest.mark.parametrize("level", list(Level))
    def test_a_count_is_never_more_than_its_share_rounded_up(self, level, count):
        mix = DifficultyMix.for_level(level, count)
        for difficulty, share in DifficultyMix.SHARES[level].items():
            assert mix.counts[difficulty] * 100 < (share * count) + 100


class TestExactCounts:
    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            (Level.BEGINNER, (3, 4, 2, 1, 0)),
            (Level.FOUNDATION, (1, 3, 4, 2, 0)),
            (Level.PROFICIENT, (0, 1, 4, 3, 2)),
            (Level.EXPERT, (0, 0, 2, 4, 4)),
        ],
    )
    def test_ten_questions_are_the_tables_percentages(self, level, expected):
        assert counts(level, 10) == expected

    @pytest.mark.parametrize(
        ("level", "count", "expected"),
        [
            # 1.5 / 2 / 1 / 0.5 / 0: easy and difficult tie on 0.5, and the easier one gets the spare question
            (Level.BEGINNER, 5, (2, 2, 1, 0, 0)),
            (Level.FOUNDATION, 5, (1, 1, 2, 1, 0)),
            (Level.PROFICIENT, 5, (0, 1, 2, 1, 1)),
            (Level.EXPERT, 5, (0, 0, 1, 2, 2)),
            (Level.BEGINNER, 15, (5, 6, 3, 1, 0)),
            (Level.BEGINNER, 25, (8, 10, 5, 2, 0)),
            (Level.PROFICIENT, 25, (0, 3, 10, 7, 5)),
        ],
    )
    def test_a_tie_goes_to_the_easier_difficulty(self, level, count, expected):
        assert counts(level, count) == expected

    def test_the_largest_remainder_wins_before_the_easier_one(self):
        # 7 questions for a Beginner: 2.1 / 2.8 / 1.4 / 0.7 / 0 → floors 2, 2, 1, 0; the two spare questions go to the
        # remainders .8 (basic) and .7 (difficult), not to the easier ones
        assert counts(Level.BEGINNER, 7) == (2, 3, 1, 1, 0)

    def test_a_count_that_divides_evenly_needs_no_rounding(self):
        assert counts(Level.FOUNDATION, 30) == (3, 9, 12, 6, 0)


class TestListing:
    def test_the_difficulties_come_easiest_first_as_often_as_asked(self):
        mix = DifficultyMix.for_level(Level.PROFICIENT, 10)

        assert mix.ordered() == [
            Difficulty.BASIC, *[Difficulty.STANDARD] * 4, *[Difficulty.DIFFICULT] * 3, *[Difficulty.EXPERT] * 2,
        ]  # fmt: skip

    def test_a_mix_of_nothing_lists_nothing(self):
        assert DifficultyMix.for_level(Level.EXPERT, 0).ordered() == []

    def test_the_total_is_the_count(self):
        assert DifficultyMix.for_level(Level.BEGINNER, 20).total == 20


class TestInput:
    def test_a_level_is_read_in_any_case(self):
        assert counts("Foundation", 10) == counts(Level.FOUNDATION, 10)

    @pytest.mark.parametrize("count", [-1, 2.5, "10", True, None])
    def test_a_count_that_is_not_a_whole_number_of_questions_is_refused(self, count):
        with pytest.raises(ValueError, match="count"):
            DifficultyMix.for_level(Level.BEGINNER, count)

    def test_an_unknown_level_is_refused(self):
        with pytest.raises(ValueError):
            DifficultyMix.for_level("genius", 10)

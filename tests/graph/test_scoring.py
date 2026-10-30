"""Unit under test: `graph.scoring.ScoreBand` and `Thresholds`, which turn marks into Fail, Normal or Excellent.

Why: the band decides whether a learner is offered a Foundation or an Advanced lesson. It must be exact at the edges
(30 and 90 percent are Normal, never Fail or Excellent), and it must never depend on floating point, where 90% of 20
marks could land a hair either side of 18.

Use cases:
- the default thresholds are 30 and 90 percent
- below the fail threshold is Fail, above the excellent threshold is Excellent, in between is Normal
- exactly 30 percent and exactly 90 percent are Normal
- 29, 30, 31, 89, 90 and 91 percent land in the right band on several totals
- a total where 90 percent is not a whole number of marks is still decided exactly
- custom thresholds are honoured
- zero marks available, marks above the total and negative marks are refused
- thresholds must be whole percents in order (0 to 100, fail not above excellent)
"""

import pytest

from graph.scoring import ScoreBand, Thresholds


class TestThresholds:
    def test_default_is_30_and_90_percent(self):
        thresholds = Thresholds()
        assert (thresholds.fail_below, thresholds.excellent_above) == (30, 90)

    @pytest.mark.parametrize(
        ("fail_below", "excellent_above"),
        [(-1, 90), (30, 101), (91, 90), (30.5, 90), (30, "90"), (True, 90)],
    )
    def test_out_of_range_unordered_or_non_integer_thresholds_are_refused(self, fail_below, excellent_above):
        with pytest.raises(ValueError):
            Thresholds(fail_below=fail_below, excellent_above=excellent_above)

    def test_equal_thresholds_are_allowed(self):
        assert Thresholds(fail_below=50, excellent_above=50).fail_below == 50


class TestScoreBand:
    @pytest.mark.parametrize("available", [10, 20, 18, 100, 7, 1000])
    @pytest.mark.parametrize(
        ("percent", "band"),
        [
            (0, ScoreBand.FAIL),
            (29, ScoreBand.FAIL),
            (30, ScoreBand.NORMAL),
            (31, ScoreBand.NORMAL),
            (89, ScoreBand.NORMAL),
            (90, ScoreBand.NORMAL),
            (91, ScoreBand.EXCELLENT),
            (100, ScoreBand.EXCELLENT),
        ],
    )
    def test_boundaries_on_several_totals(self, available, percent, band):
        # exactly `percent` percent of `available`, as a fraction of a mark where it is not whole: compare with integers
        # by scaling both sides (percent of available marks -> awarded * 100 vs percent * available)
        awarded_x100 = percent * available
        assert ScoreBand.of(awarded_x100, available * 100) is band

    @pytest.mark.parametrize(
        ("awarded", "available", "band"),
        [
            (5, 18, ScoreBand.FAIL),  # 27.7%
            (6, 18, ScoreBand.NORMAL),  # 33.3%
            (16, 18, ScoreBand.NORMAL),  # 88.9%
            (17, 18, ScoreBand.EXCELLENT),  # 94.4%; 90% of 18 is 16.2, not a whole number of marks
            (18, 18, ScoreBand.EXCELLENT),
            (5, 20, ScoreBand.FAIL),  # 25%
            (6, 20, ScoreBand.NORMAL),  # 30% exactly
            (18, 20, ScoreBand.NORMAL),  # 90% exactly
            (19, 20, ScoreBand.EXCELLENT),
            (0, 20, ScoreBand.FAIL),
        ],
    )
    def test_the_two_lesson_test_totals(self, awarded, available, band):
        assert ScoreBand.of(awarded, available) is band

    def test_a_total_where_ninety_percent_is_fractional_is_decided_exactly(self):
        # 90% of 7 marks is 6.3: 6 is under it (Normal), 7 is over it (Excellent)
        assert ScoreBand.of(6, 7) is ScoreBand.NORMAL
        assert ScoreBand.of(7, 7) is ScoreBand.EXCELLENT
        # 30% of 7 marks is 2.1: 2 is under it (Fail), 3 is over it (Normal)
        assert ScoreBand.of(2, 7) is ScoreBand.FAIL
        assert ScoreBand.of(3, 7) is ScoreBand.NORMAL

    def test_custom_thresholds_are_honoured(self):
        thresholds = Thresholds(fail_below=50, excellent_above=80)
        assert ScoreBand.of(49, 100, thresholds) is ScoreBand.FAIL
        assert ScoreBand.of(50, 100, thresholds) is ScoreBand.NORMAL
        assert ScoreBand.of(80, 100, thresholds) is ScoreBand.NORMAL
        assert ScoreBand.of(81, 100, thresholds) is ScoreBand.EXCELLENT

    @pytest.mark.parametrize(("awarded", "available"), [(0, 0), (5, 0), (1, -3), (21, 20), (-1, 20)])
    def test_zero_available_marks_more_than_available_or_negative_marks_are_refused(self, awarded, available):
        with pytest.raises(ValueError):
            ScoreBand.of(awarded, available)

    @pytest.mark.parametrize(("awarded", "available"), [(1.5, 10), (5, 10.0), ("5", 10), (None, 10), (True, 10)])
    def test_marks_must_be_integers(self, awarded, available):
        with pytest.raises(ValueError):
            ScoreBand.of(awarded, available)

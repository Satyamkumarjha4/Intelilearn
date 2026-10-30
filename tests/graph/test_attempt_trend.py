"""Unit under test: `graph.scoring.AttemptTrend`, the series of a lesson's graded attempts with the change since the
previous attempt and since the best earlier one.

Why: the history screen and the result show "better than last time" and "your best so far". The server computes it once,
from integer marks, so the two screens and every client agree. Percentages are compared, not marks, because a legacy
lesson's first attempt may have a different total.

Use cases:
- the first attempt has no change to show
- each later attempt has its change against the one before and against the best of all the earlier ones
- a tie with the best is a change of 0, and the best attempt is the earliest one that reached the top score
- a different total on the first attempt (a legacy lesson) is compared by percent
- attempts are ordered by attempt number whatever order they come in
- no attempts is an empty series with no best
- an attempt with no marks available counts as 0 percent
"""

from graph.scoring import AttemptTrend


def attempts(*scores, available=20):
    return [{"attempt_no": n, "awarded": a, "available": available} for n, a in enumerate(scores, start=1)]


def test_the_first_attempt_has_no_change():
    trend = AttemptTrend().of(attempts(10))

    (first,) = trend.series
    assert (first.percent, first.delta_previous, first.delta_best) == (50, None, None) and trend.best_attempt_no == 1


def test_each_attempt_is_compared_with_the_previous_and_with_the_best_so_far():
    trend = AttemptTrend().of(attempts(10, 16, 12, 20))

    assert [p.percent for p in trend.series] == [50, 80, 60, 100]
    assert [p.delta_previous for p in trend.series] == [None, 30, -20, 40]
    assert [p.delta_best for p in trend.series] == [None, 30, -20, 20]
    assert trend.best_attempt_no == 4


def test_a_tie_with_the_best_is_no_change_and_the_best_is_the_earlier_attempt():
    trend = AttemptTrend().of(attempts(16, 12, 16))

    assert trend.series[2].delta_best == 0 and trend.best_attempt_no == 1


def test_a_first_attempt_with_another_total_is_compared_by_percent():
    mixed = [{"attempt_no": 1, "awarded": 12, "available": 15}, {"attempt_no": 2, "awarded": 16, "available": 20}]

    trend = AttemptTrend().of(mixed)

    assert [p.percent for p in trend.series] == [80, 80] and trend.series[1].delta_previous == 0


def test_attempts_are_put_in_order_of_their_number():
    trend = AttemptTrend().of(list(reversed(attempts(4, 8, 12))))

    assert [p.attempt_no for p in trend.series] == [1, 2, 3]


def test_no_attempts_is_an_empty_series():
    trend = AttemptTrend().of([])

    assert trend.series == () and trend.best_attempt_no is None


def test_no_marks_available_counts_as_zero_percent():
    trend = AttemptTrend().of([{"attempt_no": 1, "awarded": 0, "available": 0}])

    assert trend.series[0].percent == 0

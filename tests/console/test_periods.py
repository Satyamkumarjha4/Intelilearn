"""Unit under test: `console.periods.Periods` (the three ranges the console's pages offer) and `Period`.

Why: every number on the overview is "in this range, against the one before". If the ranges overlapped, left a gap, or
started at a different hour on different pages, the same call would be counted twice or not at all, and a delta against
"before" would compare unlike things.

Use cases:
- today runs from midnight (UTC) to now; 7d and 30d from midnight that many days back (today included) to now
- the previous period is the same length and ends where the range starts, so the two never overlap or leave a gap
- the daily chart has 14 points for today and 7d and 30 for 30d, ending today
- a custom range runs from midnight of its first day to the end of its last, capped at now, with the equally long
  period before it as the previous one; it must be at most a year and not run backwards
- an unknown range is refused
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from console.periods import Periods

NOW = datetime(2026, 3, 15, 12, 30, tzinfo=UTC)
MIDNIGHT = datetime(2026, 3, 15, tzinfo=UTC)


def test_today_runs_from_midnight_to_now():
    period = Periods().of("today", NOW)

    assert (period.start, period.end) == (MIDNIGHT, NOW)
    assert (period.previous_start, period.previous_end) == (MIDNIGHT - timedelta(days=1), MIDNIGHT)


def test_seven_and_thirty_days_include_today():
    seven, thirty = Periods().of("7d", NOW), Periods().of("30d", NOW)

    assert seven.start == MIDNIGHT - timedelta(days=6)
    assert thirty.start == MIDNIGHT - timedelta(days=29)
    assert (seven.previous_start, seven.previous_end) == (seven.start - timedelta(days=7), seven.start)
    assert (thirty.previous_start, thirty.previous_end) == (thirty.start - timedelta(days=30), thirty.start)


def test_the_daily_chart_is_14_days_for_short_ranges_and_30_for_the_long_one():
    assert [Periods().of(key, NOW).chart_days for key in ("today", "7d", "30d")] == [14, 14, 30]


def test_chart_dates_end_today():
    dates = Periods().of("30d", NOW).chart_dates()

    assert len(dates) == 30 and dates[-1] == MIDNIGHT.date() and dates[0] == (MIDNIGHT - timedelta(days=29)).date()


def test_an_unknown_range_is_refused():
    with pytest.raises(ValueError, match="range"):
        Periods().of("yesterday", NOW)


def test_a_custom_range_covers_whole_days():
    period = Periods().custom(date(2026, 3, 1), date(2026, 3, 10), NOW)

    assert period.key == "custom"
    assert period.start == datetime(2026, 3, 1, tzinfo=UTC) and period.end == datetime(2026, 3, 11, tzinfo=UTC)
    assert (period.previous_start, period.previous_end) == (datetime(2026, 2, 19, tzinfo=UTC), period.start)


def test_a_custom_range_that_reaches_today_ends_now():
    period = Periods().custom(date(2026, 3, 10), date(2026, 3, 20), NOW)  # the 20th has not happened yet

    assert period.end == NOW


def test_a_custom_range_may_be_a_single_day():
    period = Periods().custom(date(2026, 3, 15), date(2026, 3, 15), NOW)

    assert (period.start, period.end) == (MIDNIGHT, NOW)


@pytest.mark.parametrize(
    ("first", "last"), [(date(2026, 3, 10), date(2026, 3, 9)), (date(2025, 1, 1), date(2026, 3, 1))]
)
def test_a_custom_range_that_runs_backwards_or_is_over_a_year_is_refused(first, last):
    with pytest.raises(ValueError, match="custom"):
        Periods().custom(first, last, NOW)

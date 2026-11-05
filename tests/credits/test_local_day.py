"""Unit under test: `credits.earning.localday.LocalDay`, a calendar day in a learner's time zone (credits plan T15).

Why: the daily credit and the streak belong to the learner's day, not to the server's. Getting the boundary wrong by
a few
hours gives a learner two credits in one evening or none for a day they studied. It is pure (an instant and a zone
name in,
a date out) so the boundary is tested to the minute, in India, which has no daylight saving, and in a zone on the
days its
clocks change, when a day is 23 or 25 hours long.

Use cases:
- an instant belongs to the day it falls in, in the learner's zone: in Asia/Kolkata the day changes at 18:30 UTC, so
  18:29Z
  is still the day and 18:31Z is the next one; midnight itself is the new day
- the same instant is a different date in different zones
- on the day the clocks go forward (23 hours) and back (25 hours) in America/New_York, the day boundaries are the local
  midnights, not 24 hours apart
- the next midnight is the first instant of the next day, in UTC
- "today" comes from the clock it is given, never from the system
- the day before and the day after are plain calendar days
- an unknown zone is refused
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from support.clock import FakeClock

from credits.earning.localday import LocalDay

KOLKATA, NEW_YORK = "Asia/Kolkata", "America/New_York"


def at(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


class TestWhichDay:
    @pytest.mark.parametrize(
        ("instant", "expected"),
        [
            (at(2026, 11, 5, 18, 29), date(2026, 11, 5)),  # 23:59 in India
            (at(2026, 11, 5, 18, 30), date(2026, 11, 6)),  # midnight itself is the new day
            (at(2026, 11, 5, 18, 31), date(2026, 11, 6)),  # 00:01
            (at(2026, 11, 5, 0, 0), date(2026, 11, 5)),  # 05:30 in India
            (at(2026, 11, 4, 18, 30), date(2026, 11, 5)),
            (at(2026, 12, 31, 18, 30), date(2027, 1, 1)),  # the year turns at 18:30Z
        ],
    )
    def test_in_india_the_day_changes_at_half_past_six_in_the_evening_utc(self, instant, expected):
        assert LocalDay.of(instant, KOLKATA).date == expected

    def test_the_same_instant_is_a_different_day_in_different_zones(self):
        instant = at(2026, 11, 5, 20, 0)

        assert LocalDay.of(instant, KOLKATA).date == date(2026, 11, 6)
        assert LocalDay.of(instant, NEW_YORK).date == date(2026, 11, 5)
        assert LocalDay.of(instant, "UTC").date == date(2026, 11, 5)
        assert LocalDay.of(instant, "Pacific/Auckland").date == date(2026, 11, 6)

    def test_an_instant_given_in_another_zone_is_converted(self):
        local = datetime(2026, 11, 5, 23, 59, tzinfo=LocalDay.zone_info(KOLKATA))

        assert LocalDay.of(local, KOLKATA).date == date(2026, 11, 5)
        assert LocalDay.of(local, "UTC").date == date(2026, 11, 5)  # 18:29Z


class TestDaylightSaving:
    def test_the_day_the_clocks_go_forward_is_23_hours_long(self):
        # 2026-03-08: 02:00 EST becomes 03:00 EDT. Midnight starting the day is 05:00Z; the next midnight is 04:00Z.
        assert LocalDay.of(at(2026, 3, 8, 4, 59), NEW_YORK).date == date(2026, 3, 7)
        assert LocalDay.of(at(2026, 3, 8, 5, 0), NEW_YORK).date == date(2026, 3, 8)
        assert LocalDay.of(at(2026, 3, 9, 3, 59), NEW_YORK).date == date(2026, 3, 8)
        assert LocalDay.of(at(2026, 3, 9, 4, 0), NEW_YORK).date == date(2026, 3, 9)

    def test_the_day_the_clocks_go_back_is_25_hours_long(self):
        # 2026-11-01: 02:00 EDT becomes 01:00 EST. Midnight starting the day is 04:00Z; the next midnight is 05:00Z.
        assert LocalDay.of(at(2026, 11, 1, 3, 59), NEW_YORK).date == date(2026, 10, 31)
        assert LocalDay.of(at(2026, 11, 1, 4, 0), NEW_YORK).date == date(2026, 11, 1)
        assert LocalDay.of(at(2026, 11, 2, 4, 59), NEW_YORK).date == date(2026, 11, 1)
        assert LocalDay.of(at(2026, 11, 2, 5, 0), NEW_YORK).date == date(2026, 11, 2)

    def test_the_next_midnight_follows_the_real_length_of_the_day(self):
        assert LocalDay.of(at(2026, 3, 8, 12, 0), NEW_YORK).next_midnight() == at(2026, 3, 9, 4, 0)
        assert LocalDay.of(at(2026, 11, 1, 12, 0), NEW_YORK).next_midnight() == at(2026, 11, 2, 5, 0)
        assert LocalDay.of(at(2026, 3, 8, 12, 0), NEW_YORK).next_midnight() - at(2026, 3, 8, 5, 0) == timedelta(
            hours=23
        )


class TestNextMidnight:
    def test_it_is_the_first_instant_of_the_next_day_in_utc(self):
        day = LocalDay.of(at(2026, 11, 5, 10, 0), KOLKATA)

        assert day.date == date(2026, 11, 5)
        assert day.next_midnight() == at(2026, 11, 5, 18, 30)
        assert LocalDay.of(day.next_midnight(), KOLKATA).date == date(2026, 11, 6)
        assert LocalDay.of(day.next_midnight() - timedelta(microseconds=1), KOLKATA).date == date(2026, 11, 5)

    def test_it_carries_across_a_month_and_a_year(self):
        assert LocalDay.of(at(2026, 12, 31, 10, 0), "UTC").next_midnight() == at(2027, 1, 1, 0, 0)
        assert LocalDay.of(at(2026, 2, 28, 10, 0), "UTC").next_midnight() == at(2026, 3, 1, 0, 0)


class TestToday:
    def test_it_comes_from_the_clock_it_is_given(self):
        clock = FakeClock(at(2026, 11, 5, 18, 29))

        assert LocalDay.today(clock, KOLKATA).date == date(2026, 11, 5)
        assert LocalDay.today(clock.advance(minutes=2), KOLKATA).date == date(2026, 11, 6)

    def test_the_zone_is_remembered(self):
        assert LocalDay.today(FakeClock(), NEW_YORK).zone == NEW_YORK


class TestNeighbours:
    def test_the_day_before_and_after_are_plain_calendar_days(self):
        day = LocalDay.of(at(2026, 3, 1, 12, 0), "UTC")

        assert day.before(1) == date(2026, 2, 28) and day.before(2) == date(2026, 2, 27)
        assert day.after(1) == date(2026, 3, 2)


def test_an_unknown_zone_is_refused():
    with pytest.raises(ValueError):
        LocalDay.of(at(2026, 11, 5), "Mars/Olympus")

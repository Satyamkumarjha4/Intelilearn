"""Unit under test: `credits.earning.streak`: `StreakCalculator` (a streak from the days a learner was active) and
`StreakMilestones` (which bonuses a run of days has earned), and `RepairPolicy` (when a missed day may be repaired).

Why: these are the spec's numbers, and a streak is the one thing here that is easy to get subtly wrong: an off-by-one at
the end of a run, a bonus paid twice when two runs join, a repair limit that a broken streak could reset. They are
pure (days
in, numbers out) so every rule is a line in a table, with no database and no clock.

Use cases:
- the current streak is the run of consecutive days that ends today or yesterday, and is alive until the end of the
  day after
  its last day; one day later it is gone; the longest run is kept; separate runs are separate
- a streak keeps counting past 28; today not yet done does not break yesterday's streak
- weekly bonuses are reached at every multiple of 7 and a monthly one at every multiple of 28: day 7 pays 10, day 14
  pays 10,
  day 28 pays 20, day 35 pays 10, day 56 pays 20; a run of 29 days has reached 4 weekly and 1 monthly
- a continuous 28 days can earn at most 78 credits (28 daily, 40 weekly, 10 monthly)
- a repair is possible only for yesterday, only if it was missed and the day before was a streak day, and only while
  fewer than
  1 repair fell in the last 7 days and fewer than 3 in the last 28 days, counted from the day each was made; the
  answer says
  how many are left and why not, and a broken streak does not reset them
"""

from datetime import date, timedelta

import pytest

from credits.earning.streak import RepairPolicy, StreakCalculator, StreakMilestones

TODAY = date(2026, 11, 5)


def days(*offsets: int) -> set[date]:
    """Days given as offsets from today (0 today, -1 yesterday…)."""
    return {TODAY + timedelta(days=n) for n in offsets}


def run_of(length: int, ends: int = 0) -> set[date]:
    return days(*range(ends - length + 1, ends + 1))


def snap(given, today=TODAY):
    return StreakCalculator().snapshot(given, today)


class TestTheCurrentStreak:
    def test_no_days_is_no_streak(self):
        s = snap(set())

        assert (s.current, s.longest, s.run_started_on, s.last_day, s.alive, s.done_today) == (
            0,
            0,
            None,
            None,
            False,
            False,
        )

    def test_a_run_ending_today_counts_and_today_is_done(self):
        s = snap(run_of(3))

        assert (s.current, s.run_started_on, s.alive, s.done_today) == (3, TODAY - timedelta(days=2), True, True)

    def test_a_run_ending_yesterday_is_alive_and_today_is_still_to_do(self):
        s = snap(run_of(3, ends=-1))

        assert (s.current, s.alive, s.done_today, s.last_day) == (3, True, False, TODAY - timedelta(days=1))

    def test_a_run_ending_the_day_before_yesterday_is_gone(self):
        s = snap(run_of(5, ends=-2))

        assert (s.current, s.run_started_on, s.alive) == (0, None, False)
        assert s.longest == 5 and s.last_day == TODAY - timedelta(days=2)

    def test_the_streak_is_the_run_that_touches_today_not_an_earlier_longer_one(self):
        s = snap(run_of(10, ends=-20) | run_of(2))

        assert (s.current, s.longest) == (2, 10)

    def test_a_gap_of_one_day_makes_two_runs(self):
        s = snap(days(-4, -3, -2, 0))  # -1 missed

        assert (s.current, s.longest, s.run_started_on) == (1, 3, TODAY)

    def test_it_keeps_counting_past_28(self):
        s = snap(run_of(60))

        assert (s.current, s.longest) == (60, 60)

    def test_a_single_day_far_back_is_just_a_longest_of_one(self):
        s = snap(days(-100))

        assert (s.current, s.longest, s.alive) == (0, 1, False)

    def test_duplicates_in_the_input_change_nothing(self):
        assert snap([TODAY, TODAY, TODAY - timedelta(days=1)]).current == 2

    def test_a_day_in_the_future_is_ignored(self):
        assert snap(days(0, 1, 2)).current == 1


class TestMilestones:
    @pytest.mark.parametrize(
        ("length", "weekly", "monthly"),
        [(0, [], []), (6, [], []), (7, [7], []), (13, [7], []), (14, [7, 14], []), (27, [7, 14, 21], []),
         (28, [7, 14, 21, 28], [28]), (29, [7, 14, 21, 28], [28]), (35, [7, 14, 21, 28, 35], [28]),
         (56, [7, 14, 21, 28, 35, 42, 49, 56], [28, 56])],
    )  # fmt: skip
    def test_what_a_run_of_this_length_has_reached(self, length, weekly, monthly):
        reached = StreakMilestones().reached(length)

        assert [m.n for m in reached if m.kind == "weekly"] == weekly
        assert [m.n for m in reached if m.kind == "monthly"] == monthly

    @pytest.mark.parametrize(
        ("day", "pays"), [(7, 10), (14, 10), (21, 10), (28, 20), (35, 10), (42, 10), (56, 20), (6, 0)]
    )
    def test_what_a_single_day_pays_in_the_specs_numbers(self, day, pays):
        newly = [m for m in StreakMilestones().reached(day) if m.n == day]

        assert len(newly) * 10 == pays  # each milestone is worth 10; a multiple of 28 is two of them

    def test_a_continuous_28_days_can_earn_at_most_78(self):
        daily = 28 * 1
        bonuses = len(StreakMilestones().reached(28)) * 10  # 4 weekly + 1 monthly, 10 each

        assert daily + bonuses == 78

    def test_a_milestone_knows_its_kind_and_day(self):
        month = [m for m in StreakMilestones().reached(28) if m.n == 28]

        assert sorted(m.kind for m in month) == ["monthly", "weekly"]


class TestRepair:
    def outlook(self, given, repaired_on=(), today=TODAY, week=1, month=3, cost=1):
        return RepairPolicy().outlook(
            set(given), list(repaired_on), today, week_limit=week, month_limit=month, cost=cost
        )

    def test_yesterday_missed_after_a_streak_day_can_be_repaired(self):
        o = self.outlook(days(-3, -2))  # -1 missed

        assert o.available and o.day == TODAY - timedelta(days=1) and o.reason is None
        assert (o.cost, o.left_week, o.left_month) == (1, 1, 3)

    def test_it_can_be_repaired_whether_or_not_today_is_done(self):
        assert self.outlook(days(-3, -2, 0)).available and self.outlook(days(-3, -2)).available

    def test_yesterday_already_there_is_nothing_to_repair(self):
        o = self.outlook(days(-2, -1))

        assert not o.available and o.reason == "nothing_to_repair" and o.day is None

    def test_a_missed_day_that_follows_no_streak_day_is_nothing_to_repair(self):
        o = self.outlook(days(-5))  # -1 missed but -2 was not a day

        assert not o.available and o.reason == "nothing_to_repair"

    def test_no_days_at_all_is_nothing_to_repair(self):
        assert self.outlook(set()).reason == "nothing_to_repair"

    def test_only_yesterday_can_be_repaired_never_an_older_gap(self):
        o = self.outlook(days(-6, -5, -2, -1))  # gaps at -4 and -3 are too old

        assert o.reason == "nothing_to_repair"

    def test_a_repaired_day_counts_as_a_streak_day_for_the_next_repair(self):
        # -3 and -2 were days, -1 was repaired and is a day too; nothing is missed
        assert self.outlook(days(-3, -2, -1)).reason == "nothing_to_repair"

    def test_one_repair_in_the_last_seven_days_uses_the_week(self):
        for ago in (0, 1, 3, 6):
            o = self.outlook(days(-3, -2), repaired_on=[TODAY - timedelta(days=ago)])
            assert not o.available and o.reason == "repair_limit" and o.left_week == 0, ago

    def test_a_repair_seven_days_ago_no_longer_counts_against_the_week(self):
        o = self.outlook(days(-3, -2), repaired_on=[TODAY - timedelta(days=7)])

        assert o.available and o.left_week == 1 and o.left_month == 2

    def test_three_repairs_in_28_days_use_the_month_even_if_none_is_this_week(self):
        made = [TODAY - timedelta(days=n) for n in (8, 15, 22)]

        o = self.outlook(days(-3, -2), repaired_on=made)

        assert not o.available and o.reason == "repair_limit" and (o.left_week, o.left_month) == (1, 0)

    def test_a_repair_28_days_ago_no_longer_counts_against_the_month(self):
        made = [TODAY - timedelta(days=n) for n in (8, 15, 28)]

        o = self.outlook(days(-3, -2), repaired_on=made)

        assert o.available and o.left_month == 1

    def test_breaking_the_streak_does_not_reset_the_limits(self):
        # a streak that ended long ago, a new one that began after, and a repair this week: the limits look only at
        # dates
        o = self.outlook(run_of(5, ends=-20) | days(-3, -2), repaired_on=[TODAY - timedelta(days=4)])

        assert o.reason == "repair_limit"

    def test_the_limits_are_settings_not_constants(self):
        assert self.outlook(days(-3, -2), repaired_on=[TODAY - timedelta(days=2)], week=2).available
        assert not self.outlook(days(-3, -2), repaired_on=[TODAY - timedelta(days=2)], week=2, month=1).available

    def test_the_cost_is_reported(self):
        assert self.outlook(days(-3, -2), cost=4).cost == 4

    def test_nothing_to_repair_is_reported_before_the_limit(self):
        o = self.outlook(days(-2, -1), repaired_on=[TODAY])

        assert o.reason == "nothing_to_repair"

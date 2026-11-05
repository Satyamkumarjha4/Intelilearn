"""The rules of streaks, bonuses and repairs as pure classes (credits plan T17, spec §4.3 and §4.4).

A streak is the run of consecutive days a learner was active (or had repaired), and it is alive until the end of the
day after
its last day. It keeps counting while it is unbroken: a weekly bonus is reached at every multiple of 7 and a monthly
one, on
top, at every multiple of 28, so day 28 pays both. Repairs are limited by counting the days they were made over
rolling windows,
which a broken streak cannot reset.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class StreakSnapshot:
    current: int  # the run touching today or yesterday; 0 once a whole day has been missed
    longest: int
    run_started_on: date | None  # the first day of the current run
    last_day: date | None  # the latest day of all, alive or not
    alive: bool
    done_today: bool


class StreakCalculator:
    def snapshot(self, days: Iterable[date], today: date) -> StreakSnapshot:
        """What the learner's days add up to as of `today` (a day in the future is ignored)."""
        ordered = sorted({day for day in days if day <= today})
        if not ordered:
            return StreakSnapshot(0, 0, None, None, False, False)
        runs: list[list[date]] = [[ordered[0]]]
        for day in ordered[1:]:
            if day - runs[-1][-1] == timedelta(days=1):
                runs[-1].append(day)
            else:
                runs.append([day])
        last_run = runs[-1]
        alive = last_run[-1] >= today - timedelta(days=1)
        return StreakSnapshot(
            current=len(last_run) if alive else 0,
            longest=max(len(run) for run in runs),
            run_started_on=last_run[0] if alive else None,
            last_day=ordered[-1],
            alive=alive,
            done_today=ordered[-1] == today,
        )


@dataclass(frozen=True)
class Milestone:
    n: int  # the day of the streak
    kind: str  # weekly or monthly


class StreakMilestones:
    WEEK, MONTH = 7, 28

    def reached(self, run_length: int) -> list[Milestone]:
        """Every bonus a run of this length has earned: a weekly one at each multiple of 7, and a monthly one as well
        at each
        multiple of 28 (so a multiple of 28 is two milestones)."""
        found = []
        for n in range(self.WEEK, run_length + 1, self.WEEK):
            found.append(Milestone(n, "weekly"))
            if n % self.MONTH == 0:
                found.append(Milestone(n, "monthly"))
        return found

    def next_after(self, run_length: int) -> int:
        """The day of the streak of the next weekly bonus."""
        return (run_length // self.WEEK + 1) * self.WEEK


@dataclass(frozen=True)
class RepairOutlook:
    available: bool
    day: date | None  # the day that would be repaired
    reason: str | None  # nothing_to_repair or repair_limit, when it is not available
    cost: int
    left_week: int
    left_month: int


class RepairPolicy:
    WEEK_DAYS, MONTH_DAYS = 7, 28

    def outlook(
        self, days: set[date], repaired_on: list[date], today: date, *, week_limit: int, month_limit: int, cost: int
    ) -> RepairOutlook:
        """On `today`, may yesterday be repaired? Only if it is missing and the day before it is a streak day, and
        only while
        fewer than `week_limit` repairs were made in the last 7 days and fewer than `month_limit` in the last 28,
        counted from
        the day each was made."""
        yesterday = today - timedelta(days=1)
        in_week = sum(1 for made in repaired_on if made > today - timedelta(days=self.WEEK_DAYS))
        in_month = sum(1 for made in repaired_on if made > today - timedelta(days=self.MONTH_DAYS))
        left_week, left_month = max(0, week_limit - in_week), max(0, month_limit - in_month)
        if yesterday in days or (today - timedelta(days=2)) not in days:
            return RepairOutlook(False, None, "nothing_to_repair", cost, left_week, left_month)
        if left_week == 0 or left_month == 0:
            return RepairOutlook(False, None, "repair_limit", cost, left_week, left_month)
        return RepairOutlook(True, yesterday, None, cost, left_week, left_month)

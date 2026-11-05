"""Studying becomes credits (credits plan T16, §5.6): the `ActivitySink` the credits app plugs in with `ACTIVITY_SINK`.

Every report says what the learner did and when. The day is that instant in the learner's own zone. The first report
of a day
writes a streak day and gives the daily credit; the streak bonuses it completes are paid; a second report the same
day does
nothing at all. The day, the credit and the bonuses are written together, so a failure leaves nothing half done and
the next
report of the day still earns it.

Not switched on yet: `ACTIVITY_SINK` stays on the do-nothing sink until the gate is switched on (phase 10.9).
"""

from datetime import date, datetime

from django.db import transaction

from lessons.activity import ActivityKind

from .earning.bonuses import StreakBonuses
from .earning.daily import DailyCredit
from .earning.days import StreakDays
from .earning.localday import LocalDay
from .earning.zone import LearnerZone
from .ledger import Ledger


class CreditsActivitySink:
    def __init__(
        self,
        ledger: Ledger | None = None,
        days: StreakDays | None = None,
        daily: DailyCredit | None = None,
        bonuses: StreakBonuses | None = None,
    ):
        self.ledger = ledger or Ledger()
        self.days = days or StreakDays(self.ledger.clock)
        self.daily = daily or DailyCredit(self.ledger)
        self.bonuses = bonuses or StreakBonuses(self.ledger)

    def record(self, user, kind: ActivityKind, at: datetime) -> None:
        day = LocalDay.of(at, LearnerZone.of(user)).date
        with transaction.atomic():
            if not self.days.add_active(user, day):
                return  # this day has already earned its credit
            self.daily.grant_for(user, day)
            self.pay_milestones(user, day)

    def pay_milestones(self, user, today: date) -> int:
        """Pay the bonuses the current streak has earned as of `today`, and bring the cached streak up to date."""
        snapshot = self.days.snapshot(user, today)
        self.days.refresh(user, snapshot)
        return self.bonuses.pay(user, snapshot)

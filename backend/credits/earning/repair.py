"""Repairing a missed day (spec §4.4, credits plan T17, D2).

On a learner's day T the day T - 1 can be repaired for a credit, if it was missed and the day before it was a streak
day, and
only while the limits hold (one repair in the last 7 days, three in the last 28, counted from the day each was made, so
breaking the streak resets nothing). A repaired day keeps the streak alive and earns no daily credit; if it completes
a bonus,
the bonus is paid then, once. The whole thing happens under the learner's wallet lock, so the rules are checked and
acted on
with nothing in between.
"""

from dataclasses import dataclass
from datetime import date

from rest_framework import status
from rest_framework.exceptions import APIException

from ..errors import InsufficientBalance
from ..ledger import Ledger
from ..models import CreditSettings
from ..refusals import InsufficientCredits
from .bonuses import StreakBonuses
from .days import StreakDays
from .localday import LocalDay
from .streak import RepairOutlook, RepairPolicy, StreakSnapshot
from .zone import LearnerZone


class NothingToRepair(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "nothing_to_repair"
    default_detail = "There is no missed day to repair."


class RepairLimitReached(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "repair_limit"
    default_detail = "You have used all the repairs you can make for now."


@dataclass(frozen=True)
class RepairResult:
    day: date
    cost: int
    streak: StreakSnapshot
    bonus: int  # credits paid because the repair completed a milestone


class StreakRepairService:
    def __init__(
        self,
        ledger: Ledger | None = None,
        days: StreakDays | None = None,
        policy: RepairPolicy | None = None,
        bonuses: StreakBonuses | None = None,
    ):
        self.ledger = ledger or Ledger()
        self.days = days or StreakDays(self.ledger.clock)
        self.policy = policy or RepairPolicy()
        self.bonuses = bonuses or StreakBonuses(self.ledger)

    def today(self, user) -> date:
        return LocalDay.today(self.ledger.clock, LearnerZone.of(user)).date

    def outlook(self, user, today: date | None = None) -> RepairOutlook:
        """Whether yesterday can be repaired now, and how many repairs are left. Reads only."""
        settings = CreditSettings.load()
        return self.policy.outlook(
            self.days.dates(user),
            self.days.repaired_on(user),
            today or self.today(user),
            week_limit=settings.repair_limit_week,
            month_limit=settings.repair_limit_month,
            cost=settings.repair_cost,
        )

    def repair(self, user) -> RepairResult:
        today = self.today(user)
        with self.ledger.exclusive(user):
            outlook = self.outlook(user, today)
            if not outlook.available:
                raise NothingToRepair() if outlook.reason == "nothing_to_repair" else RepairLimitReached()
            if outlook.cost:
                try:
                    self.ledger.debit(
                        user, outlook.cost, "streak_repair", f"repair:{user.pk}:{outlook.day}", type="repair",
                        meta={"day": str(outlook.day)},
                    )  # fmt: skip
                except InsufficientBalance as short:
                    raise InsufficientCredits(short.required, short.available) from None
            self.days.add_repaired(user, outlook.day, today)
            snapshot = self.days.snapshot(user, today)
            self.days.refresh(user, snapshot)
            bonus = self.bonuses.pay(user, snapshot)
        return RepairResult(outlook.day, outlook.cost, snapshot, bonus)

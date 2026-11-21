"""The production wiring of `SeedWorld`: the real ledger, streak days and the two API-driven steps."""

from credits.earning.days import StreakDays
from credits.earning.localday import LocalDay
from credits.earning.zone import LearnerZone
from credits.ledger import Ledger

from .api import ApiLearnerHistory, ApiPlanPurchaser
from .personas import SeedWorld


class DefaultSeedWorld:
    @staticmethod
    def build(*, history_timeout_s: float = 300) -> SeedWorld:
        ledger = Ledger()
        return SeedWorld(
            ledger=ledger,
            days=StreakDays(ledger.clock),
            purchases=ApiPlanPurchaser(),
            history=ApiLearnerHistory(timeout_s=history_timeout_s),
            today=lambda user: LocalDay.today(ledger.clock, LearnerZone.of(user)).date,
        )

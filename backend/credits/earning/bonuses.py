"""Paying the streak bonuses a run has earned (spec §4.3): +10 at every multiple of 7 and +10 more at every multiple
of 28.

Each bonus is keyed by the learner, the day the run began and the day of the streak, so it is paid once however often
the
run is looked at, and a run that broke and began again earns its own."""

from datetime import timedelta

from ..ledger import Ledger
from ..models import CreditSettings, CreditTransaction
from .streak import StreakMilestones, StreakSnapshot


class StreakBonuses:
    SOURCES = {"weekly": "weekly_streak", "monthly": "monthly_streak"}

    def __init__(self, ledger: Ledger | None = None, milestones: StreakMilestones | None = None):
        self.ledger = ledger or Ledger()
        self.milestones = milestones or StreakMilestones()

    def pay(self, user, snapshot: StreakSnapshot) -> int:
        """Pay what the current run has earned and has not been paid. → the credits paid now."""
        if not snapshot.alive or snapshot.run_started_on is None:
            return 0
        settings = CreditSettings.load()
        amounts = {"weekly": settings.weekly_streak_bonus, "monthly": settings.monthly_streak_bonus}
        prefix = f"streak:{user.pk}:{snapshot.run_started_on}:"
        paid = set(
            CreditTransaction.objects.filter(user=user, idempotency_key__startswith=prefix).values_list(
                "idempotency_key", flat=True
            )
        )
        expires = self.ledger.clock.now() + timedelta(days=settings.bonus_valid_days)
        total = 0
        for milestone in self.milestones.reached(snapshot.current):
            key = f"{prefix}{milestone.n}:{milestone.kind}"
            amount = amounts[milestone.kind]
            if key in paid or amount == 0:
                continue
            moved = self.ledger.grant(
                user, self.SOURCES[milestone.kind], amount, key, expires_at=expires, meta={"streak_day": milestone.n}
            )
            total += amount if moved.created else 0
        return total

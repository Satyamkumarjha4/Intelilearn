"""The daily credit (spec §4.2): the first activity of a learner's day earns 1 credit, in a bucket of 90 days."""

from datetime import date, timedelta

from ..ledger import Ledger, Movement
from ..models import CreditSettings


class DailyCredit:
    def __init__(self, ledger: Ledger | None = None):
        self.ledger = ledger or Ledger()

    def grant_for(self, user, day: date) -> Movement | None:
        """The credit for `day`, once: the key is the learner and the day, so asking again gives nothing more."""
        settings = CreditSettings.load()
        if settings.daily_credits == 0:
            return None
        return self.ledger.grant(
            user,
            "daily",
            settings.daily_credits,
            f"daily:{user.pk}:{day}",
            expires_at=self.ledger.clock.now() + timedelta(days=settings.bonus_valid_days),
        )

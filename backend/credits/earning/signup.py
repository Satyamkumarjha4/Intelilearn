"""The signup grant (credits plan D10, T30): 30 credits that never expire, given when an account is ready.

Given on `account_ready`, which is sent at registration today and will be sent when the email is verified once
sign-in is
built, so only the sender changes. The key is the learner, so the signal arriving twice gives it once. Accounts that
existed
before credits get it from the backfill, which is safe to run again and has a dry run."""

from dataclasses import dataclass

from accounts.models import User

from ..ledger import Ledger, Movement
from ..models import CreditSettings, CreditTransaction


@dataclass(frozen=True)
class BackfillReport:
    granted: int = 0  # accounts that got (or, in a dry run, would get) the credits
    already: int = 0  # accounts that had them
    skipped: int = 0  # closed accounts
    dry_run: bool = False


class SignupGrant:
    def __init__(self, ledger: Ledger | None = None):
        self.ledger = ledger or Ledger()

    @staticmethod
    def key(user) -> str:
        return f"signup:{user.pk}"

    def on_account_ready(self, user) -> Movement:
        return self.ledger.grant(user, "signup", CreditSettings.load().signup_credits, self.key(user))

    def backfill(self, dry_run: bool = False) -> BackfillReport:
        """Give the credits to every active account that does not have them. Closed accounts are skipped."""
        have = set(
            CreditTransaction.objects.filter(idempotency_key__startswith="signup:").values_list(
                "idempotency_key", flat=True
            )
        )
        granted = already = skipped = 0
        for user in User.objects.order_by("date_joined", "pk").iterator():
            if not user.is_active:
                skipped += 1
            elif self.key(user) in have:
                already += 1
            else:
                if not dry_run:
                    self.on_account_ready(user)
                granted += 1
        return BackfillReport(granted, already, skipped, dry_run)

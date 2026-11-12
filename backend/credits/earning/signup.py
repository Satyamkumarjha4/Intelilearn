"""The signup grant (credits plan D10, T30): 30 credits that never expire, given when an account is ready.

Given on `account_ready`, which `accounts.verification.AccountActivation` sends when an email is proved (phase 11). The
key is the learner, so the signal arriving twice gives it once. Accounts that existed before credits get it from the
backfill (verified ones only), which is safe to run again and has a dry run."""

from dataclasses import dataclass

from accounts.models import User

from ..ledger import Ledger, Movement
from ..models import CreditSettings, CreditTransaction


@dataclass(frozen=True)
class BackfillReport:
    granted: int = 0  # accounts that got (or, in a dry run, would get) the credits
    already: int = 0  # accounts that had them
    skipped: int = 0  # closed accounts
    unverified: int = 0  # active accounts whose email was never proved: no credits until it is (phase 11)
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
        """Give the credits to every active account that does not have them and whose email is verified. Closed accounts
        are skipped, and so are unverified ones (they are counted and reported): the credits are for a person who proved
        an inbox, and `account_ready` gives them the day they do."""
        have = set(
            CreditTransaction.objects.filter(idempotency_key__startswith="signup:").values_list(
                "idempotency_key", flat=True
            )
        )
        granted = already = skipped = unverified = 0
        for user in User.objects.order_by("date_joined", "pk").iterator():
            if not user.is_active:
                skipped += 1
            elif self.key(user) in have:
                already += 1
            elif not user.is_email_verified:
                unverified += 1
            else:
                if not dry_run:
                    self.on_account_ready(user)
                granted += 1
        return BackfillReport(granted, already, skipped, unverified, dry_run)

"""A learner's wallet, seen and changed from the console (credits plan §10, D12).

What is shown is read from the ledger's own tables (live buckets, the last rows), never kept anywhere else. What can be
changed is two things: credits given or taken, with a **required reason** that is kept on the ledger row and in the
change log, and the `credits_exempt` switch. Both write an `AuditEntry` with the state before and after. Giving or
taking is idempotent on the form's token, so a double click moves the credits once and is recorded once.
"""

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import User
from console.audit import AuditTrail
from credits.errors import LedgerError
from credits.ledger import Ledger
from credits.models import CreditBucket, CreditTransaction, Wallet


class WalletPanel:
    TRANSACTIONS = 50  # the most recent ledger rows shown

    def __init__(self, trail: AuditTrail, ledger: Ledger | None = None):
        self.trail = trail
        self.ledger = ledger or Ledger()

    def of(self, user_id) -> dict:
        user = self._user(user_id)
        wallet = Wallet.objects.filter(pk=user.pk).first()
        now = self.ledger.clock.now()
        live = CreditBucket.objects.filter(user=user, revoked_at__isnull=True, amount_remaining__gt=0).order_by(
            "expires_at", "created_at"
        )
        rows = CreditTransaction.objects.filter(user=user).order_by("-id")[: self.TRANSACTIONS]
        return {
            "learner": {"id": user.pk, "name": user.name, "email": user.email},
            "balance": self.ledger.balance(user),
            "reserved": self.ledger.reserved(user),
            "credits_exempt": bool(wallet and wallet.credits_exempt),
            "buckets": [
                {
                    "id": bucket.pk, "source": bucket.source, "remaining": bucket.amount_remaining,
                    "granted": bucket.amount_granted, "expires_at": bucket.expires_at,
                    "lapsed": bucket.expires_at is not None and bucket.expires_at <= now,
                    "created_at": bucket.created_at,
                }
                for bucket in live
            ],
            "transactions": [
                {
                    "id": row.pk, "type": row.type, "amount": row.amount, "balance_after": row.balance_after,
                    "action": row.action, "reason": str(row.meta.get("reason", "")), "created_at": row.created_at,
                }
                for row in rows
            ],
        }  # fmt: skip

    def adjust(self, user_id, amount: int, reason: str, token) -> dict:
        """Give (positive, never expiring) or take (negative, earliest expiry first) credits. The reason is required."""
        user = self._user(user_id)
        key = f"console:{token}:{user.pk}"
        try:
            with transaction.atomic():
                before = self.ledger.balance(user)
                moved = self.ledger.adjust(user, amount, key, reason=reason, actor=self.trail.actor.email)
                if moved.created:  # the same form sent twice moves the credits once, and is recorded once
                    self.trail.record(
                        "credits.adjust", "wallet", user.pk,
                        before={"balance": before},
                        after={"balance": self.ledger.balance(user), "amount": amount, "reason": reason.strip()},
                    )  # fmt: skip
        except LedgerError as refused:
            field = "reason" if "why" in str(refused).lower() else "amount"
            raise ValidationError({field: [str(refused)]}) from None
        return self.of(user.pk)

    def set_exempt(self, user_id, exempt: bool) -> dict:
        """Switch `credits_exempt`. Nothing is exempt by default, and being staff does not exempt anyone."""
        user = self._user(user_id)
        with transaction.atomic():
            wallet, _ = Wallet.objects.select_for_update().get_or_create(
                pk=user.pk, defaults={"created_at": timezone.now()}
            )
            if wallet.credits_exempt != exempt:
                before = wallet.credits_exempt
                wallet.credits_exempt = exempt
                wallet.save(update_fields=["credits_exempt"])
                self.trail.record(
                    "credits.exempt", "wallet", user.pk, before={"credits_exempt": before},
                    after={"credits_exempt": exempt},
                )  # fmt: skip
        return self.of(user.pk)

    @staticmethod
    def _user(user_id) -> User:
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            raise Http404
        return user

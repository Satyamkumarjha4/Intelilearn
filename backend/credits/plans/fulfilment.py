"""Turning a purchase into credits: the only path that grants plan credits (credits plan T19, §5.7). Phase 10.6's
payment
handling calls it when a payment is verified, and an administrator's "Give a plan" calls it too.

One-time credits are a bucket made at once, lasting `purchased_valid_days`, spendable immediately and on top of any
plan. A
plan is a chain of periods (`PlanChain`) queued behind the learner's last one; the first starts now, so its credits
are there
at once, and each later one grants its own when it starts. Everything happens under the learner's wallet lock and is
idempotent
on the purchase: fulfilling twice returns the same result and grants nothing more.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.db.models import Max

from ..ledger import Ledger, Movement
from ..models import CreditSettings, PlanPeriod, PlanPurchase
from .chain import PlanChain


@dataclass(frozen=True)
class FulfilmentResult:
    purchase: PlanPurchase
    periods: list[PlanPeriod] = field(default_factory=list)
    movement: Movement | None = None  # the one-time credits' ledger row
    created: bool = True  # false when the purchase had been fulfilled before


class PlanFulfilment:
    OPEN = (PlanPeriod.Status.QUEUED, PlanPeriod.Status.ACTIVE)

    def __init__(self, ledger: Ledger | None = None, chain: PlanChain | None = None):
        self.ledger = ledger or Ledger()
        self.chain = chain or PlanChain()

    def fulfil(self, purchase: PlanPurchase) -> FulfilmentResult:
        with transaction.atomic(), self.ledger.exclusive(purchase.user_id):
            purchase = PlanPurchase.objects.select_for_update().select_related("plan").get(pk=purchase.pk)
            if purchase.status == PlanPurchase.Status.FULFILLED:
                return FulfilmentResult(purchase, list(purchase.periods.order_by("position")), created=False)
            if purchase.status != PlanPurchase.Status.PENDING:
                raise ValueError(f"A {purchase.status} purchase cannot be fulfilled.")
            result = self._one_time(purchase) if purchase.plan.is_one_time else self._plan(purchase)
            purchase.status, purchase.fulfilled_at = PlanPurchase.Status.FULFILLED, self.ledger.clock.now()
            purchase.save(update_fields=["status", "fulfilled_at"])
            self.ledger.activate_periods(purchase.user_id)  # the first period starts now, so its credits are here now
            return FulfilmentResult(purchase, result.periods, result.movement)

    def _one_time(self, purchase: PlanPurchase) -> FulfilmentResult:
        days = CreditSettings.load().purchased_valid_days
        moved = self.ledger.grant(
            purchase.user_id, "purchase", purchase.credits, f"purchase:{purchase.pk}",
            expires_at=self.ledger.clock.now() + timedelta(days=days), purchase_id=purchase.pk,
            meta={"purchase": str(purchase.pk)},
        )  # fmt: skip
        return FulfilmentResult(purchase, [], moved)

    def _plan(self, purchase: PlanPurchase) -> FulfilmentResult:
        plan, now = purchase.plan, self.ledger.clock.now()
        mine = PlanPeriod.objects.filter(user_id=purchase.user_id, status__in=self.OPEN)
        spans = self.chain.periods(
            last_end=mine.aggregate(end=Max("ends_at"))["end"], now=now, period_days=plan.period_days,
            credits=plan.credits, quantity=purchase.quantity,
            limit=None,  # the room was checked when the purchase was opened; a payment taken is always honoured
        )  # fmt: skip
        made = [
            PlanPeriod.objects.create(
                user_id=purchase.user_id, purchase=purchase, position=s.position, starts_at=s.starts_at,
                ends_at=s.ends_at, credits=s.credits,
            )
            for s in spans
        ]  # fmt: skip
        return FulfilmentResult(purchase, made)

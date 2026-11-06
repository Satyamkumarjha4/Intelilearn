"""What a refund or a dispute takes back (credits plan T32, D14, §11).

The refunded share of the purchase's credits is taken back: first from periods that have not started (they hold no
credits yet, so the learner loses nothing they can use), then from what is left of the purchase's own buckets, never
going below zero and never touching credits from anywhere else. What could not be taken because it was spent is the
shortfall, recorded on the ledger row and on the event. The share is worked out from the running total refunded, so a
refund in parts takes back exactly the whole by the last of them, and a repeated key takes nothing twice.
"""

from dataclasses import dataclass

from credits.ledger import Ledger
from credits.models import PlanPeriod, PlanPurchase

from .models import PaymentOrder


@dataclass(frozen=True)
class Clawed:
    asked: int  # the credits this refund is worth
    taken: int  # what came back from the buckets and unstarted periods
    shortfall: int  # what had been spent


class ClawbackService:
    def __init__(self, ledger: Ledger | None = None):
        self.ledger = ledger or Ledger()

    def on_refund(self, order: PaymentOrder, amount_paise: int) -> Clawed:
        """`amount_paise` was refunded on `order`, whose `refunded_paise` does not include it yet."""
        purchase = PlanPurchase.objects.select_related("plan").get(pk=order.purchase_id)
        before, after = order.refunded_paise, order.refunded_paise + amount_paise
        total = self.credits_of(purchase)
        owed = total * after // order.amount_paise - total * before // order.amount_paise
        if owed <= 0:
            return Clawed(0, 0, 0)
        remaining, cancelled = owed, 0
        queued = purchase.periods.filter(status=PlanPeriod.Status.QUEUED).order_by("-position")
        for period in queued:  # not started: nothing was granted, so cancelling costs the learner nothing
            if period.credits <= remaining:
                period.status = PlanPeriod.Status.ENDED
                period.save(update_fields=["status"])
                remaining -= period.credits
                cancelled += period.credits
        taken, shortfall = cancelled, 0
        if remaining > 0:
            clawed = self.ledger.claw_back(
                order.user_id, purchase.pk, remaining, f"refund:{order.pk}:{after}", meta={"order": str(order.pk)}
            )
            taken += clawed.taken
            shortfall = clawed.shortfall
        return Clawed(owed, taken, shortfall)

    @staticmethod
    def credits_of(purchase: PlanPurchase) -> int:
        """Everything the purchase gives: the credits bought, or a plan's credits for each of its weeks."""
        return purchase.credits if purchase.plan.is_one_time else purchase.plan.credits * purchase.quantity

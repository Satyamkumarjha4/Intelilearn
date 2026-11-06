"""How an order that will not be paid ends (credits plan §5.8): `failed` or `expired`, and its purchase is voided, so
nothing waits on it and the learner's queue is not held by a payment that never came. A late payment still wins: see
`FulfilmentService`, which revives the purchase when money was taken after all."""

from django.db import transaction

from credits.clock import Clock, SystemClock
from credits.models import PlanPurchase

from .models import PaymentOrder


class OrderLifecycle:
    def __init__(self, clock: Clock | None = None):
        self.clock = clock or SystemClock()

    def fail(self, order: PaymentOrder, reason: str) -> bool:
        """End an open order as failed. False when it was no longer open (nothing changes)."""
        return self._end(order, PaymentOrder.Status.FAILED, reason)

    def expire(self, order: PaymentOrder) -> bool:
        return self._end(order, PaymentOrder.Status.EXPIRED, "expired")

    def _end(self, order: PaymentOrder, status: str, reason: str) -> bool:
        with transaction.atomic():
            fresh = PaymentOrder.objects.select_for_update().get(pk=order.pk)
            if fresh.status not in PaymentOrder.OPEN:
                return False
            fresh.status, fresh.failure_reason = status, reason[:200]
            fresh.save(update_fields=["status", "failure_reason"])
            PlanPurchase.objects.filter(pk=fresh.purchase_id, status=PlanPurchase.Status.PENDING).update(
                status=PlanPurchase.Status.VOID
            )
        order.status, order.failure_reason = status, reason[:200]
        return True

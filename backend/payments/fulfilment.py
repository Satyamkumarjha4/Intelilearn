"""Paid becomes fulfilled in one guarded step (credits plan T22, §11): the credits come from `PlanFulfilment`, which is
idempotent on the purchase, so a webhook, a reconcile and a retry that arrive together grant once. The order row is
locked first and the wallet second, everywhere, so two of them cannot wait on each other."""

from django.db import transaction

from credits.clock import Clock, SystemClock
from credits.models import PlanPurchase
from credits.plans.fulfilment import PlanFulfilment

from .models import PaymentOrder


class FulfilmentService:
    def __init__(self, plans: PlanFulfilment | None = None, clock: Clock | None = None):
        self.plans = plans or PlanFulfilment()
        self.clock = clock or self.plans.ledger.clock or SystemClock()

    def fulfil(self, order: PaymentOrder) -> PaymentOrder:
        """Grant what a paid order bought. Fulfilling a fulfilled order changes nothing; any other state is a bug."""
        with transaction.atomic():
            locked = PaymentOrder.objects.select_for_update().select_related("purchase").get(pk=order.pk)
            if locked.status == PaymentOrder.Status.FULFILLED:
                return locked
            if locked.status != PaymentOrder.Status.PAID:
                raise ValueError(f"A {locked.status} order cannot be fulfilled.")
            purchase = locked.purchase
            if purchase.status == PlanPurchase.Status.VOID:  # the payment came after the order gave up: money wins
                purchase.status = PlanPurchase.Status.PENDING
                purchase.save(update_fields=["status"])
            self.plans.fulfil(purchase)
            locked.status, locked.fulfilled_at = PaymentOrder.Status.FULFILLED, self.clock.now()
            locked.save(update_fields=["status", "fulfilled_at"])
        order.status, order.fulfilled_at = locked.status, locked.fulfilled_at
        return locked

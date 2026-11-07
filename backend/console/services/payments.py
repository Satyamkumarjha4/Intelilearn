"""The payments board: orders with their refunds and the credits a refund could not take back (credits plan §10).

Read-only. What moves money is `RefundDesk` (the refund, with its per-submission token) and `RefundDesk.mark_failed`;
this only shows what is there: each order's state, gateway and amount, what was refunded, every refund asked for with
its state, and, apart, the refund and dispute events whose credits were already spent (the shortfall that support has to
deal with).
"""

from django.db.models import Prefetch, Q, QuerySet, Sum

from payments.models import PaymentEventLog, PaymentOrder, RefundAttempt
from payments.registry import PaymentGateways


class PaymentsBoard:
    SHORTFALLS = 100  # the most shown

    def orders(self, status: str = "", gateway: str = "", search: str = "") -> QuerySet[PaymentOrder]:
        orders = (
            PaymentOrder.objects.select_related("user", "purchase__plan")
            .prefetch_related(Prefetch("refund_attempts", queryset=RefundAttempt.objects.order_by("-id")))
            .annotate(shortfall_credits=Sum("events__shortfall"))
        )
        if status:
            orders = orders.filter(status=status)
        if gateway:
            orders = orders.filter(gateway=gateway)
        if search := search.strip():
            orders = orders.filter(
                Q(user__email__icontains=search)
                | Q(user__name__icontains=search)
                | Q(provider_ref__icontains=search)
                | Q(payment_ref__icontains=search)
            )
        return orders

    def row(self, order: PaymentOrder) -> dict:
        """One order for the screen. `refunds` is every attempt, newest first, and says which a person may mark failed
        (the provider cannot be asked about it)."""
        gateway = PaymentGateways().lookup(order.gateway)
        can_ask = bool(gateway and gateway.can_fetch_refund)
        return {
            "id": order.pk,
            "learner": {"id": order.user_id, "name": order.user.name, "email": order.user.email},
            "gateway": order.gateway,
            "plan": order.purchase.plan.name,
            "amount_paise": order.amount_paise,
            "refunded_paise": order.refunded_paise,
            "currency": order.currency,
            "status": order.status,
            "provider_ref": order.provider_ref,
            "payment_ref": order.payment_ref,
            "created_at": order.created_at,
            "paid_at": order.paid_at,
            "shortfall_credits": getattr(order, "shortfall_credits", None) or 0,
            "refunds": [
                {
                    "id": attempt.pk, "amount_paise": attempt.amount_paise, "refund_ref": attempt.refund_ref,
                    "state": attempt.state, "created_at": attempt.created_at, "resolved_at": attempt.resolved_at,
                    "can_mark_failed": attempt.state == RefundAttempt.State.PENDING and not can_ask,
                }
                for attempt in order.refund_attempts.all()
            ],
        }  # fmt: skip

    def summary(self) -> dict:
        return {
            "shortfalls": PaymentEventLog.objects.filter(shortfall__gt=0).count(),
            "refunds_waiting": RefundAttempt.objects.filter(state=RefundAttempt.State.PENDING).count(),
            "orders_waiting": PaymentOrder.objects.filter(status__in=PaymentOrder.OPEN).count(),
        }

    def shortfalls(self) -> list[dict]:
        """Refunds and disputes whose credits had already been spent, newest first: what could not be taken back."""
        events = (
            PaymentEventLog.objects.filter(shortfall__gt=0)
            .select_related("order__user")
            .order_by("-id")[: self.SHORTFALLS]
        )
        return [
            {
                "id": event.pk,
                "order": event.order_id,
                "learner": {"email": event.order.user.email, "name": event.order.user.name} if event.order else None,
                "gateway": event.gateway,
                "kind": event.kind,
                "amount_paise": event.amount_paise,
                "shortfall_credits": event.shortfall,
                "received_at": event.received_at,
            }
            for event in events
        ]

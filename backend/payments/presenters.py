from credits.models import Plan

from .clawback import ClawbackService
from .models import PaymentOrder


class OrderPresenter:
    """An order as the API shows it: what it was for, what it cost, and where it stands."""

    @staticmethod
    def of(order: PaymentOrder) -> dict:
        purchase = order.purchase
        plan: Plan = purchase.plan
        return {
            "id": order.pk, "status": order.status, "gateway": order.gateway,
            "plan": {"key": plan.key, "name": plan.name}, "quantity": purchase.quantity,
            "credits": ClawbackService.credits_of(purchase), "amount_paise": order.amount_paise,
            "currency": order.currency, "refunded_paise": order.refunded_paise, "created_at": order.created_at,
            "fulfilled_at": order.fulfilled_at,
        }  # fmt: skip

    @classmethod
    def created(cls, order: PaymentOrder) -> dict:
        return {**cls.of(order), "checkout": order.checkout}

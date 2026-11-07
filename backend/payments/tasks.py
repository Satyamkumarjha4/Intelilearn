import logging

from celery import shared_task

from .reconcile import OrderReconciler
from .refund_reconcile import RefundReconciler

logger = logging.getLogger(__name__)


@shared_task(name="payments.reconcile")
def reconcile() -> dict:
    """The five-minute payments job (`CELERY_BEAT_SCHEDULE`): ask about payments whose webhook did not come, retry paid
    orders that were not fulfilled, let go of orders past their deadline, and ask about refunds still waiting.
    Idempotent. Returns the orders' counts; the refunds' are logged."""
    orders = OrderReconciler().run().as_dict()
    refunds = RefundReconciler().run().as_dict()
    if any(refunds.values()):
        logger.info("Refund sweep: %s", refunds)
    return orders

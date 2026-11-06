from celery import shared_task

from .reconcile import OrderReconciler


@shared_task(name="payments.reconcile")
def reconcile() -> dict:
    """The five-minute payments job (`CELERY_BEAT_SCHEDULE`): ask about payments whose webhook did not come, retry paid
    orders that were not fulfilled, let go of orders past their deadline. Idempotent."""
    return OrderReconciler().run().as_dict()

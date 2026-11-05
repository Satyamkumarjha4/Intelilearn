from celery import shared_task

from .tick import HourlyTick


@shared_task(name="credits.tick")
def tick() -> dict:
    """The hourly credits job (`CELERY_BEAT_SCHEDULE`): expire, reconcile reserves, audit the ledger. Idempotent."""
    return HourlyTick().run().as_dict()

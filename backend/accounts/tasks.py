from celery import shared_task

from .mail.tasks import send_mail  # noqa: F401  (registers `accounts.send_mail` with Celery)
from .purge import AccountsPurge


@shared_task(name="accounts.purge")
def purge() -> dict:
    """The daily housekeeping (`CELERY_BEAT_SCHEDULE`): forget what is past its retention. Idempotent."""
    return AccountsPurge().run().as_dict()

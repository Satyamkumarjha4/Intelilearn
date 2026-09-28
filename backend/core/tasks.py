from celery import shared_task


@shared_task
def ping() -> str:
    """Round-trip check that a worker is consuming from the broker."""
    return "pong"

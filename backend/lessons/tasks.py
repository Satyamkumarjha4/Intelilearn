"""Celery tasks: thin hooks that run a queued `GraphRun`, and the adapter the services use to queue one.

`acks_late` plus `reject_on_worker_lost` mean a task whose worker died is delivered again; `FlowRunner` then
continues the lesson's thread from its last checkpoint (and the run lock stops two workers from running it at once).
"""

from celery import shared_task
from kombu.exceptions import KombuError

from .errors import QueueUnavailable
from .models import GraphRun
from .runner import FlowRunner

RUNNER = FlowRunner  # swapped in tests


@shared_task(name="lessons.start_flow", acks_late=True, reject_on_worker_lost=True)
def start_flow(run_id: str) -> None:
    RUNNER().execute(run_id)


@shared_task(name="lessons.resume_flow", acks_late=True, reject_on_worker_lost=True)
def resume_flow(run_id: str) -> None:
    RUNNER().execute(run_id)


class CeleryTaskQueue:
    """The `TaskQueue` port: hand a queued run to a worker."""

    def __init__(self, start=start_flow, resume=resume_flow):
        self.start, self.resume = start, resume

    def enqueue(self, run: GraphRun) -> None:
        task = self.start if run.trigger == GraphRun.Trigger.START else self.resume
        try:
            result = task.apply_async(args=[str(run.id)])
        except KombuError as exc:  # the broker is unreachable
            raise QueueUnavailable() from exc
        GraphRun.objects.filter(pk=run.pk).update(celery_task_id=result.id or "")


class InlineTaskQueue:
    """The `TaskQueue` port without a worker: run the run right now, in this process (management commands)."""

    def enqueue(self, run: GraphRun) -> None:
        RUNNER().execute(run.id)

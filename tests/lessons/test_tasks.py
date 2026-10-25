"""Unit under test: `lessons.tasks`: the Celery tasks that run a queued `GraphRun`, and `CeleryTaskQueue`, the adapter
that queues one.

Why: if a start run is sent to the wrong task, or a task does not hand the run id to the runner, a learner's quiz
answers never resume their lesson. If an unreachable broker is not reported, the learner waits for a lesson that was
never started.

Use cases:
- both tasks hand the run id to the runner
- a start run goes to start_flow and every other trigger to resume_flow, and the Celery task id is recorded
- an unreachable broker is reported as the queue being unavailable
- the tasks are registered with Celery under their documented names and acknowledge late
"""

import pytest
from kombu.exceptions import OperationalError

from config.celery import app
from lessons import tasks
from lessons.errors import QueueUnavailable
from lessons.models import GraphRun
from lessons.tasks import CeleryTaskQueue


class FakeTask:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def apply_async(self, args):
        if self.fail:
            raise OperationalError("broker down")
        self.calls.append(args)
        return type("Result", (), {"id": "task-123"})()


def test_both_tasks_hand_the_run_id_to_the_runner(monkeypatch):
    seen = []

    class FakeRunner:
        def execute(self, run_id):
            seen.append(run_id)

    monkeypatch.setattr(tasks, "RUNNER", FakeRunner)

    tasks.start_flow("run-1")
    tasks.resume_flow("run-2")

    assert seen == ["run-1", "run-2"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("trigger", "expected"),
    [
        (GraphRun.Trigger.START, "start"),
        (GraphRun.Trigger.RESUME_DIAGNOSTIC, "resume"),
        (GraphRun.Trigger.RESUME_PREREQUISITE, "resume"),
        (GraphRun.Trigger.RESUME_CHOICE, "resume"),
        (GraphRun.Trigger.RETRY, "resume"),
    ],
)
def test_a_start_run_goes_to_start_flow_and_every_other_trigger_to_resume_flow(lesson, trigger, expected):
    run = GraphRun.objects.create(lesson=lesson, trigger=trigger)
    start, resume = FakeTask(), FakeTask()

    CeleryTaskQueue(start=start, resume=resume).enqueue(run)

    assert {"start": start, "resume": resume}[expected].calls == [[str(run.id)]]
    assert (start.calls == []) == (expected == "resume")
    run.refresh_from_db()
    assert run.celery_task_id == "task-123"


@pytest.mark.django_db
def test_an_unreachable_broker_is_reported_as_the_queue_being_unavailable(lesson):
    run = GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START)

    with pytest.raises(QueueUnavailable):
        CeleryTaskQueue(start=FakeTask(fail=True)).enqueue(run)


def test_the_tasks_are_registered_under_their_documented_names_and_acknowledge_late():
    for name in ("lessons.start_flow", "lessons.resume_flow"):
        task = app.tasks[name]
        assert task.acks_late is True and task.reject_on_worker_lost is True

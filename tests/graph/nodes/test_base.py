"""Unit under test: `graph.nodes.base.Node`, the callable every graph node is built on.

Why: LangGraph runs nodes on pool threads, and Django gives each thread its own database connection. If a node left
its connection open, every lesson run would leak connections until Postgres refused new ones. A node that declares its
stage also keeps the lesson's stage honest when the thread has moved on without it: after a Stop and a Retry the
lesson is put back in the stage it was stopped in, which can be one the thread has already left (a Stop that lands just
after a quiz is answered, or before a self-rated lesson's first step finishes), and the build would then fail at its
last step.

Use cases:
- a node run on a worker thread closes that thread's database connection when it ends, even if it raised
- a node run on the main thread (tests, management commands) leaves the connection alone
- a node of a building stage moves a failed lesson to it (a Retry), and a lesson still reading as one of the waiting
  stages (preparing, or waiting for a quiz or the choice) to it, as a Retry can put it back too far; a node never moves
  a lesson that is in any other stage, a node of a waiting stage never moves a lesson on, and a node that declares no
  stage never moves it
- a node may choose its working stage from the state (a lesson that is only sheets works in "writing the study sheet"
  where a lesson works in "building the lesson"), and the same corrections then move the lesson to that one
"""

import threading

import pytest
from django.db import connection

from graph.nodes.base import Node
from lessons.models import Lesson, Stage

pytestmark = pytest.mark.django_db(transaction=True)


class TouchesTheDatabase(Node):
    name = "touch"

    def __init__(self, fail: bool = False):
        self.fail = fail

    def run(self, state, ctx):
        Lesson.objects.count()
        if self.fail:
            raise RuntimeError("boom")
        return {}


def run_on_thread(node, runtime) -> dict:
    """→ whether the thread's connection was open before and after the node, and what the node raised."""
    seen: dict = {}

    def target():
        try:
            node({"lesson_id": "x"}, runtime)
        except RuntimeError as exc:
            seen["error"] = str(exc)
        seen["open_after"] = connection.connection is not None

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    return seen


def test_a_node_on_a_worker_thread_closes_its_connection(runtime):
    assert run_on_thread(TouchesTheDatabase(), runtime) == {"open_after": False}


def test_a_failing_node_on_a_worker_thread_still_closes_its_connection(runtime):
    assert run_on_thread(TouchesTheDatabase(fail=True), runtime) == {"error": "boom", "open_after": False}


class Declares(Node):
    def __init__(self, stage):
        self.stage = stage

    name = "declares"

    def run(self, state, ctx):
        return {}


@pytest.mark.parametrize(("before", "declared", "after"), [
    (Stage.FAILED, Stage.GENERATING_LESSON, Stage.GENERATING_LESSON),
    (Stage.FAILED, Stage.PREPARING_DIAGNOSTIC, Stage.PREPARING_DIAGNOSTIC),
    (Stage.PREPARING_DIAGNOSTIC, Stage.GENERATING_LESSON, Stage.GENERATING_LESSON),
    (Stage.PREPARING_DIAGNOSTIC, Stage.GENERATING_MATERIAL, Stage.GENERATING_MATERIAL),
    (Stage.PREPARING_DIAGNOSTIC, Stage.PREPARING_DIAGNOSTIC, Stage.PREPARING_DIAGNOSTIC),
    (Stage.AWAITING_DIAGNOSTIC, Stage.GENERATING_LESSON, Stage.GENERATING_LESSON),  # a Stop just after the answer
    (Stage.AWAITING_PREREQUISITE, Stage.GENERATING_LESSON, Stage.GENERATING_LESSON),
    (Stage.AWAITING_CHOICE, Stage.GENERATING_LESSON, Stage.GENERATING_LESSON),
    (Stage.AWAITING_CHOICE, Stage.GENERATING_MATERIAL, Stage.GENERATING_MATERIAL),
    (Stage.AWAITING_DIAGNOSTIC, Stage.AWAITING_PREREQUISITE, Stage.AWAITING_DIAGNOSTIC),  # never on
    (Stage.GENERATING_MATERIAL, Stage.GENERATING_LESSON, Stage.GENERATING_MATERIAL),
    (Stage.GENERATING_LESSON, Stage.PREPARING_DIAGNOSTIC, Stage.GENERATING_LESSON),
    (Stage.READY, Stage.GENERATING_LESSON, Stage.READY),
])  # fmt: skip
def test_a_node_that_declares_a_stage_corrects_only_a_failed_or_too_early_lesson(
    lesson, runtime, before, declared, after
):
    Lesson.objects.filter(pk=lesson.pk).update(stage=before, error="boom")

    Declares(declared)({"lesson_id": str(lesson.pk)}, runtime)

    assert Lesson.objects.get(pk=lesson.pk).stage == after


class ChoosesItsStage(Node):
    """A node whose working stage depends on what the lesson is for: building a lesson, or writing sheets only."""

    name = "chooses"

    def stage_of(self, state):
        return Stage.GENERATING_MATERIAL if state.get("intent") == "sheets" else Stage.GENERATING_LESSON

    def run(self, state, ctx):
        return {}


@pytest.mark.parametrize(("intent", "after"), [
    ("sheets", Stage.GENERATING_MATERIAL), ("lesson", Stage.GENERATING_LESSON), (None, Stage.GENERATING_LESSON),
])  # fmt: skip
def test_a_node_that_chooses_its_stage_from_the_state_corrects_to_that_one(lesson, runtime, intent, after):
    Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED, error="boom")

    ChoosesItsStage()({"lesson_id": str(lesson.pk), "intent": intent}, runtime)

    assert Lesson.objects.get(pk=lesson.pk).stage == after


def test_a_node_that_declares_no_stage_never_moves_the_lesson(lesson, runtime):
    Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.PREPARING_DIAGNOSTIC)

    Declares(None)({"lesson_id": str(lesson.pk)}, runtime)

    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.PREPARING_DIAGNOSTIC


def test_a_node_on_the_main_thread_leaves_the_connection_open(runtime):
    TouchesTheDatabase()({"lesson_id": "x"}, runtime)

    assert connection.connection is not None

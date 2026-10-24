"""Unit under test: `graph.nodes.failure.MarkFailedNode` and `AwaitRetryNode`, the end of a run that gave up.

Why: when a model keeps producing invalid output the learner must see a readable reason and be able to press Retry.
Recording the failure and waiting are split in two nodes because a node that waits runs again from the top on resume;
if it also wrote the failure, a retry would re-mark the lesson as failed.

Use cases:
- mark_failed records the state's error on the lesson and moves it to failed
- mark_failed falls back to a generic message when none was set
- mark_failed does not touch a lesson that is already ready
- await_retry has no side effects of its own (it only waits); its resume behaviour is covered in test_builders
"""

from graph.nodes.failure import MarkFailedNode
from lessons.models import Lesson, Stage


def test_mark_failed_records_the_error_and_moves_the_lesson_to_failed(lesson, lesson_state, runtime):
    update = MarkFailedNode()(lesson_state | {"error": "The diagnostic quiz still failed its checks"}, runtime)

    stored = Lesson.objects.get(pk=lesson.pk)
    assert update == {}
    assert (stored.stage, stored.error) == (Stage.FAILED, "The diagnostic quiz still failed its checks")


def test_mark_failed_uses_a_generic_message_when_none_was_set(lesson, lesson_state, runtime):
    MarkFailedNode()(lesson_state, runtime)

    assert Lesson.objects.get(pk=lesson.pk).error == "The lesson could not be built."


def test_mark_failed_leaves_a_finished_lesson_alone(lesson, lesson_state, runtime):
    Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)

    MarkFailedNode()(lesson_state | {"error": "late failure"}, runtime)

    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY

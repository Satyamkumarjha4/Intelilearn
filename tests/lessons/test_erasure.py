"""Unit under test: `lessons.erasure.LessonErasure` and `CheckpointThreads`, which remove what a deleted lesson leaves
outside the rows Django cascades: its LangGraph checkpoints and its model-call log.

Why: both can hold the learner's words (their answers and the lesson text sit in checkpoint state, and the call log
keeps the prompts' metadata). A delete that leaves them behind breaks the promise of "delete" and the privacy notes in
docs/architecture/data-model.md; deleting too much would wipe another learner's lesson mid-build.

Use cases:
- erasing a lesson deletes its flow thread and the thread of each small graph run (`lesson:run`), nothing else
- a lesson with no runs still has its flow thread deleted
- erasing deletes the lesson's model calls and keeps every other lesson's
- the checkpoint rows of the real tables are removed for the lesson's thread only
- a database without checkpoint tables has nothing to delete, so it is not an error
- any other database error is not swallowed
"""

import uuid

import psycopg
import pytest
from django.db import connection
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from lessons.checkpoints import CheckpointerFactory
from lessons.erasure import CheckpointThreads, LessonErasure
from lessons.models import GraphRun
from llm_registry.models import ModelCall

pytestmark = pytest.mark.django_db


class FakeThreads:
    def __init__(self):
        self.deleted: list[str] = []

    def delete(self, thread_ids):
        self.deleted.extend(thread_ids)


def make_call(lesson_id):
    return ModelCall.objects.create(
        lesson_id=lesson_id, node_key="n", provider_key="p", model_name="m", attempt=1, fallback_index=0,
        status="ok", latency_ms=1,
    )  # fmt: skip


class TestLessonErasure:
    def test_deletes_the_flow_thread_and_each_small_graph_thread_of_the_lesson_only(self, make_lesson):
        mine, theirs = make_lesson(), make_lesson()
        GraphRun.objects.create(lesson=mine, trigger=GraphRun.Trigger.START)
        sheet = GraphRun.objects.create(
            lesson=mine, graph=GraphRun.Graph.STUDY_MATERIAL, trigger=GraphRun.Trigger.EXTRA_MATERIAL
        )
        grading = GraphRun.objects.create(lesson=mine, graph=GraphRun.Graph.GRADE_TEST, trigger=GraphRun.Trigger.GRADE)
        GraphRun.objects.create(lesson=theirs, trigger=GraphRun.Trigger.START)
        threads = FakeThreads()

        LessonErasure(threads).erase(mine)

        assert sorted(threads.deleted) == sorted([str(mine.id), f"{mine.id}:{sheet.id}", f"{mine.id}:{grading.id}"])

    def test_a_lesson_with_no_runs_still_has_its_flow_thread_deleted(self, lesson):
        threads = FakeThreads()

        LessonErasure(threads).erase(lesson)

        assert threads.deleted == [str(lesson.id)]

    def test_deletes_the_lessons_model_calls_and_keeps_every_other_lessons(self, make_lesson):
        mine, theirs = make_lesson(), make_lesson()
        make_call(mine.id), make_call(mine.id)
        kept = make_call(theirs.id)
        unattached = make_call(None)

        LessonErasure(FakeThreads()).erase(mine)

        assert set(ModelCall.objects.all()) == {kept, unattached}


class Counter(TypedDict):
    n: int


def counter_graph(checkpointer):
    graph = StateGraph(Counter)
    graph.add_node("inc", lambda state: {"n": state.get("n", 0) + 1})
    graph.add_edge(START, "inc")
    graph.add_edge("inc", END)
    return graph.compile(checkpointer=checkpointer)


class TestCheckpointThreads:
    def test_removes_the_checkpoints_of_the_given_threads_only(self):
        factory = CheckpointerFactory(connection.settings_dict)
        factory.setup()
        gone, kept = f"test-{uuid.uuid4()}", f"test-{uuid.uuid4()}"
        with factory.saver() as saver:
            for thread in (gone, kept):
                counter_graph(saver).invoke({"n": 1}, {"configurable": {"thread_id": thread}})

        CheckpointThreads(factory).delete([gone])

        with factory.saver() as saver:
            assert counter_graph(saver).get_state({"configurable": {"thread_id": gone}}).values == {}
            assert counter_graph(saver).get_state({"configurable": {"thread_id": kept}}).values == {"n": 2}

    def test_a_database_without_checkpoint_tables_has_nothing_to_delete(self):
        factory = BrokenFactory(psycopg.errors.UndefinedTable("relation checkpoints does not exist"))

        CheckpointThreads(factory).delete(["any"])  # does not raise

    def test_any_other_database_error_is_raised(self):
        factory = BrokenFactory(psycopg.errors.OperationalError("connection lost"))

        with pytest.raises(psycopg.errors.OperationalError):
            CheckpointThreads(factory).delete(["any"])


class BrokenFactory:
    """A checkpointer factory whose saver fails the way a database would."""

    def __init__(self, error):
        self.error = error

    def saver(self):
        error = self.error

        class Saver:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def delete_thread(self, thread_id):
                raise error

        return Saver()

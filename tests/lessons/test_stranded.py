"""Unit under test: `lessons.stranded`: `PendingNodes` (what a checkpoint is about to run), `StrandedThreads` (the
lessons whose thread waits at, or would resume into, a node the current graph no longer has) and the
`stranded_threads` management command that lists them and can mark them failed.

Why: a lesson can wait at a quiz for days, and a release that removes or renames a graph node (9.2 removed `write_test`)
leaves such a thread pointing at nothing. LangGraph does not complain: it shows no pending step and, on resume, quietly
ends the run, so the learner sees a lesson that never moves. The deploy notes say stranded threads are drained: this
command finds them from the raw checkpoint (the compiled graph hides them) and marks each failed with a message that
tells the learner to start a new lesson.

Use cases:
- a checkpoint reports the nodes whose trigger was written but not yet consumed, and ignores the ones that already ran
  (also when the checkpoint was written to Postgres, as it is in production)
- a checkpoint reports a node waiting to start through a `Send` as well
- a thread that waits at a node the current graph has is not stranded, and neither is one that has ended
- a thread that waits at a node the current graph lacks is stranded, and names that node
- a thread at the retry pause whose `failed_node` is gone is stranded, and names that node
- a thread at the retry pause whose `failed_node` still exists is not stranded
- a ready lesson is never reported, and a lesson that has no thread is skipped
- a real lesson-flow thread paused at a quiz is found once the quiz node is taken out of the graph
- marking failed gives the lesson a clear reason, moves it to failed, leaves a ready lesson alone and says how many
  changed; running it again changes nothing
- the command lists the stranded lessons and says so when there are none; without `--mark-failed` it changes nothing;
  with it, the lessons are marked failed
"""

from contextlib import contextmanager
from io import StringIO

import pytest
from django.core.management import call_command
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from support.driver import GraphDriver
from typing_extensions import TypedDict

from graph.builders import AuthorSegment, DiagnoseSegment, FlowGraphBuilder
from lessons.checkpoints import CheckpointerFactory
from lessons.management.commands.stranded_threads import Command
from lessons.models import Lesson, Stage
from lessons.stranded import PendingNodes, StrandedThreads

pytestmark = pytest.mark.django_db


class State(TypedDict, total=False):
    x: int
    failed_node: str


def step(state):
    return {"x": 1}


def waits(state):
    interrupt({"kind": "k"})
    return {}


def graph_with(*nodes, edges, saver, conditional=None, interrupt_before=None):
    graph = StateGraph(State)
    for name in nodes:
        graph.add_node(name, waits if name.startswith("wait") or name == "await_retry" else step)
    for source, target in edges:
        graph.add_edge(source, target)
    for source, router, targets in conditional or []:
        graph.add_conditional_edges(source, router, targets)
    return graph.compile(checkpointer=saver, interrupt_before=interrupt_before)


class InMemoryFactory:
    def __init__(self, saver):
        self._saver = saver

    @contextmanager
    def saver(self):
        yield self._saver


def run_to_pause(saver, lesson, *, old_node="wait_old", state=None):
    """An old release: start → one step → a node that waits. Returns the config of the paused thread."""
    graph = graph_with("start_step", old_node, edges=[(START, "start_step"), ("start_step", old_node), (old_node, END)],
                       saver=saver)  # fmt: skip
    config = {"configurable": {"thread_id": str(lesson.id)}}
    graph.invoke(state or {"x": 0}, config)
    return config


def checkpoint_of(saver, config):
    return saver.get_tuple(config).checkpoint


class TestPendingNodes:
    def test_a_node_whose_trigger_was_written_but_not_consumed_is_pending(self, lesson):
        saver = InMemorySaver()
        config = run_to_pause(saver, lesson)

        assert PendingNodes().of(checkpoint_of(saver, config)) == {"wait_old"}

    def test_a_node_that_already_ran_is_not_pending(self, lesson):
        saver = InMemorySaver()
        graph = graph_with("one", "two", edges=[(START, "one"), ("one", "two"), ("two", END)], saver=saver)
        config = {"configurable": {"thread_id": str(lesson.id)}}
        graph.invoke({"x": 0}, config)

        assert PendingNodes().of(checkpoint_of(saver, config)) == set()

    def test_a_node_waiting_to_start_through_a_send_is_pending(self, lesson):
        saver = InMemorySaver()

        def fan(state):
            return [Send("worker", {"x": 1})]

        graph = graph_with("emit", "worker", edges=[(START, "emit"), ("worker", END)], saver=saver,
                           conditional=[("emit", fan, ["worker"])], interrupt_before=["worker"])  # fmt: skip
        config = {"configurable": {"thread_id": str(lesson.id)}}
        graph.invoke({"x": 0}, config)

        assert "worker" in PendingNodes().of(checkpoint_of(saver, config))

    def test_the_target_of_a_retry_pause_is_the_failed_node(self, lesson):
        saver = InMemorySaver()
        config = run_to_pause(saver, lesson, old_node="await_retry", state={"x": 0, "failed_node": "write_test"})

        assert PendingNodes().resumes_into(checkpoint_of(saver, config)) == "write_test"

    def test_a_thread_not_at_the_retry_pause_resumes_into_nothing_extra(self, lesson):
        saver = InMemorySaver()
        config = run_to_pause(saver, lesson, state={"x": 0, "failed_node": "write_test"})

        assert PendingNodes().resumes_into(checkpoint_of(saver, config)) is None


class TestInPostgres:
    def test_the_checkpoint_the_postgres_saver_writes_reads_the_same_way(self, lesson):
        factory = CheckpointerFactory()
        factory.setup()
        with factory.saver() as saver:
            config = run_to_pause(saver, lesson)

            pending = PendingNodes().of(checkpoint_of(saver, config))
            found = StrandedThreads(checkpointers=factory, node_names=lambda: {"start_step"}).find()

        assert pending == {"wait_old"} and [t.missing for t in found] == [("wait_old",)]


class TestStrandedThreads:
    def finder(self, saver, nodes):
        return StrandedThreads(checkpointers=InMemoryFactory(saver), node_names=lambda: set(nodes))

    def test_a_thread_waiting_at_a_node_the_graph_has_is_not_stranded(self, lesson):
        saver = InMemorySaver()
        run_to_pause(saver, lesson)

        assert self.finder(saver, {"start_step", "wait_old"}).find() == []

    def test_a_thread_waiting_at_a_node_the_graph_lacks_is_stranded_and_names_it(self, lesson):
        saver = InMemorySaver()
        run_to_pause(saver, lesson)

        (found,) = self.finder(saver, {"start_step", "wait_new"}).find()

        assert found.lesson_id == lesson.pk and found.missing == ("wait_old",)
        assert found.topic == lesson.topic and found.stage == lesson.stage

    def test_a_thread_that_has_ended_is_not_stranded(self, lesson):
        saver = InMemorySaver()
        graph = graph_with("only", edges=[(START, "only"), ("only", END)], saver=saver)
        graph.invoke({"x": 0}, {"configurable": {"thread_id": str(lesson.id)}})

        assert self.finder(saver, {"other"}).find() == []

    def test_a_thread_at_the_retry_pause_is_stranded_when_its_failed_node_is_gone(self, lesson):
        saver = InMemorySaver()
        run_to_pause(saver, lesson, old_node="await_retry", state={"x": 0, "failed_node": "write_test"})

        (found,) = self.finder(saver, {"start_step", "await_retry"}).find()

        assert found.missing == ("write_test",)

    def test_a_thread_at_the_retry_pause_is_fine_when_its_failed_node_still_exists(self, lesson):
        saver = InMemorySaver()
        run_to_pause(saver, lesson, old_node="await_retry", state={"x": 0, "failed_node": "plan_lesson"})

        assert self.finder(saver, {"start_step", "await_retry", "plan_lesson"}).find() == []

    def test_a_ready_lesson_is_never_reported(self, lesson):
        saver = InMemorySaver()
        run_to_pause(saver, lesson)
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)

        assert self.finder(saver, {"nothing"}).find() == []

    def test_a_lesson_with_no_thread_is_skipped(self, lesson):
        assert self.finder(InMemorySaver(), {"nothing"}).find() == []

    def test_a_real_flow_thread_paused_at_a_quiz_is_found_once_that_node_is_removed(self, lesson, ctx, lesson_state,
                                                                                    gateway, valid_bundle):  # fmt: skip
        gateway.script("diagnostic.generate", valid_bundle)
        driver = GraphDriver(lesson, ctx, lesson_state, [DiagnoseSegment(), AuthorSegment()])
        driver.start()
        assert driver.interrupt["kind"] == "diagnostic"
        saver = driver.graph.checkpointer
        current = set(FlowGraphBuilder().build().nodes) - {"await_diagnostic"}

        (found,) = self.finder(saver, current).find()

        assert found.lesson_id == lesson.pk and found.missing == ("await_diagnostic",)

    def test_marking_failed_gives_a_clear_reason_and_says_how_many_changed(self, lesson):
        saver = InMemorySaver()
        run_to_pause(saver, lesson)
        finder = self.finder(saver, {"start_step", "wait_new"})

        changed = finder.mark_failed(finder.find())

        fresh = Lesson.objects.get(pk=lesson.pk)
        assert changed == 1 and fresh.stage == Stage.FAILED
        assert "started before an update" in fresh.error and "start a new lesson" in fresh.error.lower()

    def test_marking_failed_leaves_a_ready_lesson_alone_and_a_repeat_changes_nothing(self, lesson):
        saver = InMemorySaver()
        run_to_pause(saver, lesson)
        finder = self.finder(saver, {"start_step", "wait_new"})
        found = finder.find()
        finder.mark_failed(found)
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)

        assert finder.mark_failed(found) == 0
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY


class TestCommand:
    def run(self, saver, *args, nodes=("start_step", "wait_new")):
        out = StringIO()
        finder = StrandedThreads(checkpointers=InMemoryFactory(saver), node_names=lambda: set(nodes))
        call_command(Command(finder=finder), *args, stdout=out)
        return out.getvalue()

    def test_it_lists_the_stranded_lessons(self, lesson):
        saver = InMemorySaver()
        run_to_pause(saver, lesson)

        output = self.run(saver)

        assert str(lesson.pk) in output and "wait_old" in output and lesson.topic in output

    def test_it_says_so_when_there_are_none(self, lesson):
        assert "No stranded threads" in self.run(InMemorySaver())

    def test_without_the_flag_it_changes_nothing(self, lesson):
        saver = InMemorySaver()
        run_to_pause(saver, lesson)

        self.run(saver)

        assert Lesson.objects.get(pk=lesson.pk).stage != Stage.FAILED

    def test_with_the_flag_it_marks_the_lessons_failed_and_says_how_many(self, lesson):
        saver = InMemorySaver()
        run_to_pause(saver, lesson)

        output = self.run(saver, "--mark-failed")

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.FAILED and "Marked 1 lesson as failed" in output

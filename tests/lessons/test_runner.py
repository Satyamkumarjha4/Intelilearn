"""Unit under test: `lessons.runner.FlowRunner` (executes one `GraphRun` segment of a lesson's graph), with its
collaborators `GraphRunRecorder`, `RunLock` and `FailureMessage`.

Why: this is the seam between the web app and the graph. If it mislabels a pause as a failure the learner is told their
lesson broke while it is waiting for them; if a redelivered task runs the graph twice, or restarts it from scratch, work
is duplicated or lost; if a model failure is not turned into a readable message and a retry point, the learner is
stuck. Tests run the real graph with a scripted gateway.

Use cases:
- a start run streams the graph to the first quiz and ends paused, with progress events and the quiz kind
- a resume run continues the same thread from its checkpoint and ends succeeded with a done event
- the prerequisite route pauses a second time, for the prerequisite quiz
- node progress is recorded on the run as it happens
- a validation failure the graph gives up on ends the run failed with the readable reason, and Retry resumes it
- a model failure ends the run failed with a friendly message, fails the lesson, and Retry re-runs the failed node
- a run that is already finished, or that another worker holds, is not executed again
- a redelivered run that was left running continues from its checkpoint
- a cancelled run stops after the current node and publishes cancelled
- an unknown graph fails the run with a clear message
- a thread paused by one runner is resumed by another with a fresh Postgres checkpointer (a restarted worker)
- failure messages: model failures name the step, unexpected errors do not leak details
- the recorder and lock behave: begin is conditional, finish only from running, the lock is exclusive
"""

import contextlib

import pytest
from django.db import connection
from langgraph.checkpoint.memory import InMemorySaver
from support.fakes import FakeSandbox

from graph.context import FlowContext
from graph.grading import QuizGrader
from graph.registry import GraphRegistry
from lessons.checkpoints import CheckpointerFactory
from lessons.events import RunEvent
from lessons.models import GraphRun, Lesson, Quiz, QuizAttempt, Stage
from lessons.runner import FailureMessage, FlowRunner, GraphRunRecorder, RunLock
from llm_registry.gateway import AllModelsFailed, NodeDisabled

# LangGraph runs a node on a worker thread, which has its own database connection: it only sees committed rows.
pytestmark = pytest.mark.django_db(transaction=True)

ASSESSMENT = {
    "level": "beginner", "known_concepts": [], "gaps": ["x"], "prerequisites_to_cover": [],
    "start_point": "Halving", "author_notes": "Gentle.", "confidence": "medium",
}  # fmt: skip


class ListPublisher:
    def __init__(self):
        self.published: list[tuple[str, RunEvent]] = []

    def publish(self, run_id, event):
        self.published.append((str(run_id), event))

    def names(self):
        return [event.name for _, event in self.published]

    def of(self, name):
        return [event.data for _, event in self.published if event.name == name]


class SharedMemory:
    """A checkpointer 'factory' whose saver (and so its checkpoints) outlives each execution, like a database."""

    def __init__(self):
        self._saver = InMemorySaver()

    @contextlib.contextmanager
    def saver(self):
        yield self._saver


@pytest.fixture
def publisher():
    return ListPublisher()


@pytest.fixture
def checkpoints():
    return SharedMemory()


@pytest.fixture
def make_runner(gateway, publisher, checkpoints):
    def _make(**overrides):
        def context(run_id):
            return FlowContext(gateway=gateway, sandbox=FakeSandbox(), run_id=run_id)

        options = {"checkpointers": checkpoints, "events": publisher, "context_factory": context} | overrides
        return FlowRunner(**options)

    return _make


@pytest.fixture
def prepared(lesson, flow_settings, make_snapshot_for_nodes):
    Lesson.objects.filter(pk=lesson.pk).update(
        config_snapshot=make_snapshot_for_nodes(), settings_snapshot=flow_settings
    )
    return lesson


def new_run(lesson, trigger=GraphRun.Trigger.START, payload=None, graph="flow"):
    return GraphRun.objects.create(lesson=lesson, trigger=trigger, payload=payload or {}, graph=graph)


def attempt(lesson, kind, right):
    quiz = Quiz.objects.get(lesson=lesson, kind=kind)
    answers = {q["id"]: q["correct_index"] if n < right else (q["correct_index"] + 1) % 4
               for n, q in enumerate(quiz.questions)}  # fmt: skip
    return QuizAttempt.objects.create(
        quiz=quiz, answers=answers, result=QuizGrader().grade(quiz.questions, answers).as_dict()
    )


def test_a_start_run_streams_to_the_first_quiz_and_ends_paused(make_runner, prepared, gateway, publisher, valid_bundle):
    gateway.script("diagnostic.generate", valid_bundle)
    run = new_run(prepared)

    result = make_runner().execute(run.id)

    run.refresh_from_db()
    assert result.pk == run.pk
    assert run.status == GraphRun.Status.PAUSED and run.started_at and run.finished_at
    quiz = Quiz.objects.get(lesson=prepared, kind="diagnostic")
    assert publisher.of("awaiting_input") == [{"kind": "diagnostic", "quiz_id": str(quiz.id)}]
    assert publisher.names()[-1] == "awaiting_input"
    assert {"node": "load_context", "status": "running"} in publisher.of("node")
    assert {"node": "publish_diagnostic", "status": "done"} in publisher.of("node")
    assert Lesson.objects.get(pk=prepared.pk).stage == Stage.AWAITING_DIAGNOSTIC


def test_the_events_are_published_on_the_runs_own_channel(make_runner, prepared, gateway, publisher, valid_bundle):
    gateway.script("diagnostic.generate", valid_bundle)
    run = new_run(prepared)

    make_runner().execute(run.id)

    assert {run_id for run_id, _ in publisher.published} == {str(run.id)}


def test_node_progress_is_recorded_on_the_run(make_runner, prepared, gateway, valid_bundle):
    gateway.script("diagnostic.generate", valid_bundle)
    run = new_run(prepared)

    make_runner().execute(run.id)

    run.refresh_from_db()
    assert run.node_status["load_context"] == "done"
    assert run.node_status["generate_diagnostic"] == "done"
    assert run.node_status["publish_diagnostic"] == "done"


def test_a_resume_run_continues_the_thread_and_ends_succeeded(make_runner, prepared, gateway, publisher, valid_bundle):
    gateway.script("diagnostic.generate", valid_bundle).script("learner.assess", ASSESSMENT)
    make_runner().execute(new_run(prepared).id)
    answered = attempt(prepared, "diagnostic", right=5)
    resume = new_run(prepared, GraphRun.Trigger.RESUME_DIAGNOSTIC, {"resume": str(answered.id)})

    make_runner().execute(resume.id)  # a different runner, as when another worker picks the task up

    resume.refresh_from_db()
    assert resume.status == GraphRun.Status.SUCCEEDED
    assert publisher.of("done") == [{"lesson_id": str(prepared.id), "stage": "generating_lesson"}]
    stored = Lesson.objects.get(pk=prepared.pk)
    assert stored.route == "lesson" and stored.assessment["start_point"] == "Halving"
    assert len(gateway.called("diagnostic.generate")) == 1  # the quiz was not generated again


def test_a_poor_score_pauses_again_for_the_prerequisite_quiz(make_runner, prepared, gateway, publisher, valid_bundle):
    gateway.script("diagnostic.generate", valid_bundle)
    make_runner().execute(new_run(prepared).id)
    answered = attempt(prepared, "diagnostic", right=0)
    resume = new_run(prepared, GraphRun.Trigger.RESUME_DIAGNOSTIC, {"resume": str(answered.id)})

    make_runner().execute(resume.id)

    resume.refresh_from_db()
    assert resume.status == GraphRun.Status.PAUSED
    assert publisher.of("awaiting_input")[-1]["kind"] == "prerequisite"
    assert Lesson.objects.get(pk=prepared.pk).stage == Stage.AWAITING_PREREQUISITE


def test_a_validation_failure_the_graph_gives_up_on_fails_the_run_and_retry_resumes_it(
    make_runner, prepared, gateway, publisher, valid_bundle
):
    bad = {**valid_bundle, "diagnostic": valid_bundle["diagnostic"][:9]}
    gateway.script("diagnostic.generate", bad, bad, valid_bundle)
    run = new_run(prepared)

    make_runner().execute(run.id)

    run.refresh_from_db()
    assert run.status == GraphRun.Status.FAILED
    assert "still failed its checks after 2 attempts" in run.error
    assert publisher.of("error")[-1]["message"] == run.error
    assert Lesson.objects.get(pk=prepared.pk).stage == Stage.FAILED

    retry = new_run(prepared, GraphRun.Trigger.RETRY)
    make_runner().execute(retry.id)

    retry.refresh_from_db()
    assert retry.status == GraphRun.Status.PAUSED
    assert Lesson.objects.get(pk=prepared.pk).stage == Stage.AWAITING_DIAGNOSTIC


def test_a_model_failure_fails_the_run_with_a_friendly_message_and_retry_reruns_the_node(
    make_runner, prepared, gateway, publisher, valid_bundle
):
    gateway.script("diagnostic.generate", AllModelsFailed("diagnostic.generate", ["gemini: 401"]), valid_bundle)
    run = new_run(prepared)

    make_runner().execute(run.id)

    run.refresh_from_db()
    stored = Lesson.objects.get(pk=prepared.pk)
    assert run.status == GraphRun.Status.FAILED
    assert "diagnostic.generate" in run.error and "model registry" in run.error
    assert (stored.stage, stored.error) == (Stage.FAILED, run.error)
    assert publisher.of("error")[-1] == {"message": run.error, "code": "failed"}

    retry = new_run(prepared, GraphRun.Trigger.RETRY)
    make_runner().execute(retry.id)

    retry.refresh_from_db()
    assert retry.status == GraphRun.Status.PAUSED
    assert len(gateway.called("diagnostic.generate")) == 2
    assert Lesson.objects.get(pk=prepared.pk).error == ""


@pytest.mark.parametrize("status", [GraphRun.Status.SUCCEEDED, GraphRun.Status.FAILED, GraphRun.Status.CANCELLED])
def test_a_finished_run_is_not_executed_again(make_runner, prepared, gateway, publisher, status):
    run = new_run(prepared)
    GraphRun.objects.filter(pk=run.pk).update(status=status)

    make_runner().execute(run.id)

    assert gateway.calls == [] and publisher.published == []
    run.refresh_from_db()
    assert run.status == status


def test_a_run_another_worker_holds_is_not_executed(make_runner, prepared, gateway, valid_bundle):
    run = new_run(prepared)
    lock = RunLock()
    assert lock.acquire(run.id)

    make_runner(lock=lock).execute(run.id)

    run.refresh_from_db()
    assert run.status == GraphRun.Status.QUEUED and gateway.calls == []


def test_the_lock_is_released_when_the_run_ends(make_runner, prepared, gateway, valid_bundle):
    gateway.script("diagnostic.generate", valid_bundle)
    run = new_run(prepared)

    make_runner().execute(run.id)

    assert RunLock().acquire(run.id)


def test_a_redelivered_run_left_running_continues_from_its_checkpoint(
    make_runner, prepared, gateway, publisher, valid_bundle
):
    gateway.script("diagnostic.generate", valid_bundle).script("learner.assess", ASSESSMENT)
    make_runner().execute(new_run(prepared).id)
    answered = attempt(prepared, "diagnostic", right=5)
    resume = new_run(prepared, GraphRun.Trigger.RESUME_DIAGNOSTIC, {"resume": str(answered.id)})
    GraphRun.objects.filter(pk=resume.pk).update(status=GraphRun.Status.RUNNING)

    make_runner().execute(resume.id)
    make_runner().execute(resume.id)  # delivered twice: the second finds the thread already finished

    resume.refresh_from_db()
    assert resume.status == GraphRun.Status.SUCCEEDED
    assert len(gateway.called("learner.assess")) == 1


def test_a_cancelled_run_stops_after_the_current_node(make_runner, prepared, gateway, publisher, valid_bundle):
    run = new_run(prepared)

    def cancel_while_generating(messages):
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.CANCELLED)
        return valid_bundle

    gateway.script("diagnostic.generate", cancel_while_generating)

    make_runner().execute(run.id)

    run.refresh_from_db()
    assert run.status == GraphRun.Status.CANCELLED
    assert publisher.names()[-1] == "cancelled"
    assert "validate_diagnostic" not in run.node_status
    assert Quiz.objects.filter(lesson=prepared).count() == 0


def test_an_unknown_graph_fails_the_run_with_a_clear_message(make_runner, prepared):
    run = new_run(prepared, graph="runtime_repair")

    make_runner(graphs=GraphRegistry()).execute(run.id)

    run.refresh_from_db()
    assert run.status == GraphRun.Status.FAILED
    assert "Unknown graph" in run.error
    assert Lesson.objects.get(pk=prepared.pk).stage == Stage.PREPARING_DIAGNOSTIC  # only the main flow fails a lesson


def test_a_restarted_worker_resumes_a_paused_lesson_from_the_postgres_checkpoint(
    make_runner, prepared, gateway, publisher, valid_bundle
):
    factory = CheckpointerFactory(connection.settings_dict)
    factory.setup()
    gateway.script("diagnostic.generate", valid_bundle).script("learner.assess", ASSESSMENT)
    make_runner(checkpointers=factory).execute(new_run(prepared).id)
    answered = attempt(prepared, "diagnostic", right=5)
    resume = new_run(prepared, GraphRun.Trigger.RESUME_DIAGNOSTIC, {"resume": str(answered.id)})

    make_runner(checkpointers=CheckpointerFactory(connection.settings_dict)).execute(resume.id)  # new objects

    resume.refresh_from_db()
    assert resume.status == GraphRun.Status.SUCCEEDED
    assert len(gateway.called("diagnostic.generate")) == 1


class TestFailureMessage:
    def test_a_model_failure_names_the_step_and_points_at_the_registry(self):
        message = FailureMessage().of(AllModelsFailed("page.generate", ["gemini: 429"]))

        assert "page.generate" in message and "model registry" in message and "gemini: 429" in message

    def test_a_disabled_node_says_so(self):
        message = FailureMessage().of(NodeDisabled("lesson.plan is disabled in the registry"))

        assert "lesson.plan is disabled" in message

    def test_an_unexpected_error_names_its_type_but_not_its_details(self):
        message = FailureMessage().of(RuntimeError("password=hunter2 host=10.0.0.5"))

        assert "RuntimeError" in message and "hunter2" not in message


class TestRecorder:
    def test_begin_marks_a_queued_run_running_once(self, prepared):
        run = new_run(prepared)
        recorder = GraphRunRecorder()

        assert recorder.begin(run) is True
        started = run.started_at
        assert recorder.begin(run) is True  # redelivery of a running run
        assert run.started_at == started and run.status == GraphRun.Status.RUNNING

    def test_begin_refuses_a_run_that_was_cancelled_meanwhile(self, prepared):
        run = new_run(prepared)
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.CANCELLED)

        assert GraphRunRecorder().begin(run) is False

    def test_finish_only_moves_a_running_run(self, prepared):
        run = new_run(prepared)
        recorder = GraphRunRecorder()
        recorder.begin(run)
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.CANCELLED)

        recorder.finish(run, GraphRun.Status.SUCCEEDED)

        run.refresh_from_db()
        assert run.status == GraphRun.Status.CANCELLED  # the cancel wins

    def test_finish_records_the_error_and_the_time(self, prepared):
        run = new_run(prepared)
        recorder = GraphRunRecorder()
        recorder.begin(run)

        recorder.finish(run, GraphRun.Status.FAILED, "boom")

        run.refresh_from_db()
        assert (run.status, run.error) == (GraphRun.Status.FAILED, "boom") and run.finished_at

    def test_records_node_events_only(self, prepared):
        run = new_run(prepared)
        recorder = GraphRunRecorder()

        recorder.record(run, RunEvent("node", {"node": "plan_lesson", "status": "running"}))
        recorder.record(run, RunEvent("warning", {"message": "x"}))
        recorder.record(run, RunEvent("node", {"node": "plan_lesson", "status": "done"}))

        run.refresh_from_db()
        assert run.node_status == {"plan_lesson": "done"}


class TestRunLock:
    def test_only_one_holder_at_a_time(self):
        lock = RunLock()

        assert lock.acquire("r") is True
        assert lock.acquire("r") is False
        lock.release("r")
        assert lock.acquire("r") is True

    def test_locks_are_per_run(self):
        lock = RunLock()

        assert lock.acquire("a") and lock.acquire("b")

    def test_refreshing_a_lock_that_expired_is_harmless(self):
        RunLock().refresh("never-held")

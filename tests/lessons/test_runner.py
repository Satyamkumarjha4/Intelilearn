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
- Retry after a stop carries on from the checkpoint, however far the graph got: a stop between a node's end and the
  next step leaves tasks that are done but not applied, and that is not "finished"; it is never a no-op that leaves the
  lesson failed
- a resume run stopped before the worker took it is retried with the answer the learner already gave, not a bare True
- a stop noticed after the graph had already paused again retries into that pause (the old answer is not fed to a
  different question), and the lesson is back at that quiz's stage
- an error that surfaces in a node after the learner stopped the run does not replace the "Cancelled" message
- an unknown graph fails the run with a clear message
- an extra study sheet runs in its own thread, ends succeeded and leaves the lesson ready
- an extra sheet that fails its checks ends the run failed with the reason and leaves the lesson alone
- a runtime repair runs in its own thread, saves a new code version and leaves the lesson ready
- a repair that cannot be made safely ends the run failed with the reason and leaves the lesson's code alone
- a test grading run saves the score card on its submission; a grading that cannot finish fails the run and marks the
  submission failed, so the learner can submit again
- a thread paused by one runner is resumed by another with a fresh Postgres checkpointer (a restarted worker)
- failure messages: model failures name the step, unexpected errors do not leak details
- the recorder and lock behave: begin is conditional, finish only from running, the lock is exclusive
- the recorder keeps when each node started and finished, and how often the graph ran it again (the console timeline)
"""

import contextlib
from datetime import UTC, datetime

import pytest
from django.db import connection
from django.utils import timezone
from langgraph.checkpoint.memory import InMemorySaver
from support.fakes import FakeSandbox
from support.fixtures import budget_snapshot
from support.lesson_data import make_final_test, make_state
from support.quiz_data import make_questions
from support.study_data import CONCEPTS, make_practice_sheet, make_revision_sheet

from graph.builders import FlowGraphBuilder
from graph.context import FlowContext
from graph.errors import RunFailed
from graph.grading import QuizGrader
from graph.registry import GraphRegistry
from graph.sandbox import RenderReport
from lessons.checkpoints import CheckpointerFactory
from lessons.events import RunEvent
from lessons.models import GraphRun, Lesson, LessonVersion, Quiz, QuizAttempt, Stage, StudyMaterial, TestSubmission
from lessons.runner import FailureMessage, FlowRunner, GraphRunRecorder, RunLock
from lessons.services import LessonService
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
def make_runner(gateway, publisher, checkpoints, stage_a_graphs):
    def _make(**overrides):
        def context(run_id):
            return FlowContext(gateway=gateway, sandbox=FakeSandbox(), run_id=run_id)

        options = {
            "graphs": stage_a_graphs,
            "checkpointers": checkpoints,
            "events": publisher,
            "context_factory": context,
        } | overrides
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


class TestRetryAfterAStop:
    """The learner pressed Stop (`LessonService.cancel`, as the API does), then Retry."""

    @pytest.fixture
    def service(self, queue, publisher):
        return LessonService(queue=queue, events=publisher)

    def stop_in(self, service, run, gateway, node_key, answer):
        """Script `node_key` so that the learner stops the run while the model is answering."""

        def stop_then_answer(messages):
            service.cancel(GraphRun.objects.select_related("lesson").get(pk=run.pk))
            return answer

        gateway.script(node_key, stop_then_answer)

    def test_a_stop_while_the_quiz_is_being_written_is_retried_from_the_saved_node(
        self, service, make_runner, prepared, gateway, valid_bundle
    ):
        run = new_run(prepared)
        self.stop_in(service, run, gateway, "diagnostic.generate", valid_bundle)
        make_runner().execute(run.id)
        assert Lesson.objects.get(pk=prepared.pk).stage == Stage.FAILED

        retry = service.retry(Lesson.objects.get(pk=prepared.pk))
        make_runner().execute(retry.id)

        retry.refresh_from_db()
        stored = Lesson.objects.get(pk=prepared.pk)
        assert retry.status == GraphRun.Status.PAUSED
        assert (stored.stage, stored.error) == (Stage.AWAITING_DIAGNOSTIC, "")
        assert Quiz.objects.filter(lesson=prepared, kind="diagnostic").count() == 1
        assert len(gateway.called("diagnostic.generate")) == 1  # the saved answer was used, not asked for again

    def test_a_stop_while_the_learner_is_assessed_is_retried_to_the_end_of_the_graph(
        self, service, make_runner, prepared, gateway, publisher, valid_bundle
    ):
        gateway.script("diagnostic.generate", valid_bundle)
        make_runner().execute(new_run(prepared).id)
        answered = attempt(prepared, "diagnostic", right=5)
        resume = new_run(prepared, GraphRun.Trigger.RESUME_DIAGNOSTIC, {"resume": str(answered.id)})
        self.stop_in(service, resume, gateway, "learner.assess", ASSESSMENT)
        make_runner().execute(resume.id)
        assert Lesson.objects.get(pk=prepared.pk).stage == Stage.FAILED

        retry = service.retry(Lesson.objects.get(pk=prepared.pk))
        make_runner().execute(retry.id)

        retry.refresh_from_db()
        stored = Lesson.objects.get(pk=prepared.pk)
        assert retry.status == GraphRun.Status.SUCCEEDED
        assert publisher.of("done")[-1] == {"lesson_id": str(prepared.id), "stage": "generating_lesson"}
        assert (stored.stage, stored.route, stored.error) == (Stage.GENERATING_LESSON, "lesson", "")
        assert stored.assessment["start_point"] == "Halving"
        assert len(gateway.called("learner.assess")) == 1

    def test_a_resume_run_stopped_before_the_worker_took_it_is_retried_with_the_answer_already_given(
        self, service, make_runner, prepared, gateway, valid_bundle
    ):
        gateway.script("diagnostic.generate", valid_bundle).script("learner.assess", ASSESSMENT)
        make_runner().execute(new_run(prepared).id)
        answered = attempt(prepared, "diagnostic", right=5)
        resume = new_run(prepared, GraphRun.Trigger.RESUME_DIAGNOSTIC, {"resume": str(answered.id)})
        service.cancel(resume)
        make_runner().execute(resume.id)  # the worker finds it cancelled and does nothing

        retry = service.retry(Lesson.objects.get(pk=prepared.pk))
        make_runner().execute(retry.id)

        retry.refresh_from_db()
        stored = Lesson.objects.get(pk=prepared.pk)
        assert retry.status == GraphRun.Status.SUCCEEDED
        assert retry.payload["resume"] == str(answered.id)
        assert (stored.stage, stored.route) == (Stage.GENERATING_LESSON, "lesson")
        assert QuizAttempt.objects.filter(quiz__lesson=prepared).count() == 1  # the answers were not asked for again

    def test_a_stop_noticed_after_the_graph_paused_again_retries_into_that_pause(
        self, service, make_runner, prepared, gateway, publisher, valid_bundle
    ):
        gateway.script("diagnostic.generate", valid_bundle)
        make_runner().execute(new_run(prepared).id)
        answered = attempt(prepared, "diagnostic", right=0)  # a poor score: the prerequisite quiz comes next
        resume = new_run(prepared, GraphRun.Trigger.RESUME_DIAGNOSTIC, {"resume": str(answered.id)})
        make_runner().execute(resume.id)
        assert Lesson.objects.get(pk=prepared.pk).stage == Stage.AWAITING_PREREQUISITE
        # The Stop came while the worker was wrapping up, so the run row says cancelled although the graph paused.
        GraphRun.objects.filter(pk=resume.pk).update(status=GraphRun.Status.RUNNING)
        service.cancel(GraphRun.objects.select_related("lesson").get(pk=resume.pk))
        assert Lesson.objects.get(pk=prepared.pk).stage == Stage.FAILED

        retry = service.retry(Lesson.objects.get(pk=prepared.pk))
        make_runner().execute(retry.id)

        retry.refresh_from_db()
        assert retry.status == GraphRun.Status.PAUSED and retry.error == ""
        assert publisher.of("awaiting_input")[-1]["kind"] == "prerequisite"
        stored = Lesson.objects.get(pk=prepared.pk)
        assert (stored.stage, stored.error) == (Stage.AWAITING_PREREQUISITE, "")
        assert QuizAttempt.objects.filter(quiz__lesson=prepared).count() == 1  # the diagnostic answer was not replayed

    def test_an_error_after_the_stop_does_not_replace_the_cancelled_message(
        self, service, make_runner, prepared, gateway, publisher
    ):
        run = new_run(prepared)

        def stop_then_break(messages):
            service.cancel(GraphRun.objects.select_related("lesson").get(pk=run.pk))
            raise RuntimeError("the connection dropped")

        gateway.script("diagnostic.generate", stop_then_break)

        make_runner().execute(run.id)

        run.refresh_from_db()
        stored = Lesson.objects.get(pk=prepared.pk)
        assert run.status == GraphRun.Status.CANCELLED
        assert stored.stage == Stage.FAILED and stored.error.startswith("Cancelled")
        assert publisher.names()[-1] == "cancelled" and publisher.of("error") == []


def test_an_unknown_graph_fails_the_run_with_a_clear_message(make_runner, prepared):
    run = new_run(prepared, graph="runtime_repair")

    make_runner(graphs=GraphRegistry({"flow": FlowGraphBuilder(segments=[])})).execute(run.id)

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


def ready_mastery_lesson(lesson):
    questions = [{**q, "concept": CONCEPTS[n % 2]} for n, q in enumerate(make_questions())]
    Quiz.objects.create(lesson=lesson, kind="diagnostic", questions=questions)
    Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY, route="mastery")
    return lesson


def extra_run(lesson, kind):
    payload = {"input": {"mastery_choice": kind, "extra_material": True}}
    return new_run(lesson, GraphRun.Trigger.EXTRA_MATERIAL, payload, graph="study_material")


def test_an_extra_sheet_runs_in_its_own_thread_and_leaves_the_lesson_ready(make_runner, prepared, gateway, publisher):
    ready_mastery_lesson(prepared)
    gateway.script("study.generate", make_revision_sheet())
    run = extra_run(prepared, "revision_sheet")

    make_runner().execute(run.id)

    run.refresh_from_db()
    assert run.status == GraphRun.Status.SUCCEEDED
    assert publisher.of("done") == [{"lesson_id": str(prepared.id), "stage": "ready"}]
    assert StudyMaterial.objects.get(lesson=prepared).kind == "revision_sheet"
    assert FlowRunner.thread_id(run) == f"{prepared.id}:{run.id}"


def test_an_extra_sheet_that_fails_its_checks_fails_the_run_but_not_the_lesson(
    make_runner, prepared, gateway, publisher
):
    ready_mastery_lesson(prepared)
    short = make_practice_sheet(14)
    gateway.script("study.generate", short, short)
    run = extra_run(prepared, "practice_sheet")

    make_runner().execute(run.id)

    run.refresh_from_db()
    assert run.status == GraphRun.Status.FAILED and "The practice sheet still failed its checks" in run.error
    assert publisher.of("error")[-1]["message"] == run.error
    assert Lesson.objects.get(pk=prepared.pk).stage == Stage.READY and not StudyMaterial.objects.exists()


REPAIR_PARTS = {
    "pages": {k: f"function Page_{k}() {{ return <Interactive_w />; }}" for k in ("introduction", "core", "advanced")},
    "interactives": {"Interactive_w": "function Interactive_w() { return null.x; }"},
}  # fmt: skip


def broken_ready_lesson(lesson, flow_settings):
    full = make_state()
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, code="OLD", code_parts=REPAIR_PARTS, code_version=1, plan=full["plan"], pages=full["pages"],
        final_test=full["final_test"], config_snapshot=budget_snapshot(), settings_snapshot=flow_settings,
    )  # fmt: skip
    payload = {"input": {"repair_error": {"message": "Interactive_w crashed"}, "expected_code_version": 1}}
    return new_run(lesson, GraphRun.Trigger.REPAIR, payload, graph="runtime_repair")


def test_a_runtime_repair_runs_in_its_own_thread_and_leaves_the_lesson_ready(
    make_runner, gateway, publisher, prepared, flow_settings
):
    run = broken_ready_lesson(prepared, flow_settings)
    gateway.script("runtime.repair", "function Interactive_w() { return <b>ok</b>; }")
    sandbox = FakeSandbox(render_reports=[RenderReport(ok=True)])

    make_runner(context_factory=lambda run_id: FlowContext(gateway=gateway, sandbox=sandbox)).execute(run.id)

    run.refresh_from_db()
    assert run.status == GraphRun.Status.SUCCEEDED and publisher.of("done") == [
        {"lesson_id": str(prepared.id), "stage": "ready"}
    ]
    stored = Lesson.objects.get(pk=prepared.pk)
    assert (stored.code_version, stored.stage) == (2, Stage.READY) and "<b>ok</b>" in stored.code
    assert LessonVersion.objects.get(lesson=prepared).code == "OLD"


def test_a_repair_that_cannot_be_made_safely_fails_the_run_and_leaves_the_code_alone(
    make_runner, gateway, publisher, prepared, flow_settings
):
    run = broken_ready_lesson(prepared, flow_settings)
    gateway.script("runtime.repair", REPAIR_PARTS["interactives"]["Interactive_w"])

    make_runner(context_factory=lambda run_id: FlowContext(gateway=gateway, sandbox=FakeSandbox())).execute(run.id)

    run.refresh_from_db()
    assert run.status == GraphRun.Status.FAILED and "same code" in run.error
    assert publisher.of("error")[-1]["message"] == run.error
    stored = Lesson.objects.get(pk=prepared.pk)
    assert (stored.code, stored.code_version, stored.stage) == ("OLD", 1, Stage.READY)
    assert not LessonVersion.objects.exists()


def grading_run(lesson, flow_settings, answers):
    final_test = make_final_test()
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, final_test=final_test, config_snapshot=budget_snapshot(), settings_snapshot=flow_settings
    )
    submission = TestSubmission.objects.create(lesson=lesson, answers=answers)
    payload = {"input": {"submission_id": str(submission.id)}}
    return submission, new_run(lesson, GraphRun.Trigger.GRADE, payload, graph="grade_test"), final_test


def test_a_grading_run_saves_the_score_card_on_its_submission(make_runner, gateway, publisher, prepared, flow_settings):
    ids = {q["type"]: q["id"] for q in make_final_test()["questions"]}
    submission, run, _ = grading_run(prepared, flow_settings, {ids["mcq"]: 1, ids["short_answer"]: "Halve it."})
    gateway.script("test.grade", {"grades": [{"question_id": ids["short_answer"], "awarded": 2, "feedback": "Good."}]})
    sandbox = FakeSandbox()

    make_runner(context_factory=lambda run_id: FlowContext(gateway=gateway, sandbox=sandbox)).execute(run.id)

    run.refresh_from_db()
    submission.refresh_from_db()
    assert run.status == GraphRun.Status.SUCCEEDED and submission.status == "graded"
    assert submission.result["score"]["awarded"] == 4 and submission.result["complete"] is True
    assert publisher.of("done") == [{"lesson_id": str(prepared.id), "stage": "ready"}]
    assert FlowRunner.thread_id(run) == f"{prepared.id}:{run.id}"


def test_a_grading_that_cannot_finish_fails_the_run_and_the_submission_but_not_the_lesson(
    make_runner, gateway, publisher, prepared, flow_settings
):
    ids = {q["type"]: q["id"] for q in make_final_test()["questions"]}
    submission, run, _ = grading_run(prepared, flow_settings, {ids["short_answer"]: "Halve it."})
    gateway.scripts["test.grade"] = [AllModelsFailed("test.grade", ["gemini: 429"])]

    make_runner(context_factory=lambda run_id: FlowContext(gateway=gateway, sandbox=FakeSandbox())).execute(run.id)

    run.refresh_from_db()
    submission.refresh_from_db()
    assert run.status == GraphRun.Status.FAILED and "test.grade" in run.error
    assert submission.status == "failed" and submission.error == run.error
    assert Lesson.objects.get(pk=prepared.pk).stage == Stage.READY
    assert publisher.of("error")[-1]["message"] == run.error


class TestFailureMessage:
    def test_a_deliberate_failure_is_shown_as_written(self):
        assert FailureMessage().of(RunFailed("The cheat sheet still failed its checks")) == (
            "The cheat sheet still failed its checks"
        )

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


class TestRecorderTimings:
    def at(self, hour, minute=0):
        return datetime(2026, 3, 1, hour, minute, tzinfo=UTC)

    def record(self, recorder, run, node, status, when, monkeypatch):
        monkeypatch.setattr(timezone, "now", lambda: when)
        recorder.record(run, RunEvent("node", {"node": node, "status": status}))

    def test_a_node_gets_its_start_and_finish_time(self, prepared, monkeypatch):
        run, recorder = new_run(prepared), GraphRunRecorder()

        self.record(recorder, run, "plan_lesson", "running", self.at(10), monkeypatch)
        self.record(recorder, run, "plan_lesson", "done", self.at(10, 5), monkeypatch)

        run.refresh_from_db()
        assert run.node_timings == {
            "plan_lesson": {
                "started_at": "2026-03-01T10:00:00+00:00",
                "finished_at": "2026-03-01T10:05:00+00:00",
                "retries": 0,
            }  # fmt: skip
        }

    def test_a_node_that_has_not_finished_has_no_finish_time(self, prepared, monkeypatch):
        run, recorder = new_run(prepared), GraphRunRecorder()

        self.record(recorder, run, "await_diagnostic", "running", self.at(10), monkeypatch)

        run.refresh_from_db()
        assert run.node_timings["await_diagnostic"]["finished_at"] is None

    def test_a_node_that_runs_again_keeps_its_first_start_and_its_last_finish_and_counts_the_retries(
        self, prepared, monkeypatch
    ):
        run, recorder = new_run(prepared), GraphRunRecorder()

        self.record(recorder, run, "generate_diagnostic", "running", self.at(10), monkeypatch)
        self.record(recorder, run, "generate_diagnostic", "retrying", self.at(10, 1), monkeypatch)
        self.record(recorder, run, "generate_diagnostic", "running", self.at(10, 2), monkeypatch)
        self.record(recorder, run, "generate_diagnostic", "done", self.at(10, 3), monkeypatch)

        run.refresh_from_db()
        assert run.node_timings["generate_diagnostic"] == {
            "started_at": "2026-03-01T10:00:00+00:00",
            "finished_at": "2026-03-01T10:03:00+00:00",
            "retries": 1,
        }

    def test_a_failed_or_degraded_node_is_finished_too(self, prepared, monkeypatch):
        run, recorder = new_run(prepared), GraphRunRecorder()

        self.record(recorder, run, "render_check", "failed", self.at(11), monkeypatch)
        self.record(recorder, run, "verify_media", "degraded", self.at(11, 1), monkeypatch)

        run.refresh_from_db()
        assert run.node_timings["render_check"]["finished_at"] == "2026-03-01T11:00:00+00:00"
        assert run.node_timings["verify_media"]["finished_at"] == "2026-03-01T11:01:00+00:00"


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

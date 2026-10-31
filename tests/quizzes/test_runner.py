"""Unit under test: `lessons.runner.FlowRunner` and `lessons.effects.RunEffects` for the runs of a quick quiz: the
`quick_quiz` graph (a quiz's questions, and every retake's) and the `grade_quiz` graph.

Why: a run that belongs to a quiz instead of a lesson must be streamed, paused, resumed, failed and stopped by the very
same machinery, and what it leaves behind when it dies must be tidy: a quiz that never got its questions is failed, a
retake that could not be written leaves no half-made attempt (so the attempt number is not used up), an attempt whose
grading died can be graded again, and the action gate is told how it ended. The calibration walk pauses a run and the
one resume must continue the same thread.

Use cases:
- a self-rated quiz's start run streams to the end, starts the waiting attempt, makes the quiz ready and reports `done`
- the walk's start run pauses the quiz for calibration (an `awaiting_input` event of that kind), and the resume run
  continues the same thread to the end
- the thread of a quiz's first run and of its resume is the quiz's own; every retake and grading run has a thread of its
  own
- a model failure while a quiz is being made fails the quiz with a readable reason and removes the waiting attempt; on a
  retake the quiz stays ready and the waiting attempt goes
- stopping a run removes the waiting attempt, fails a quiz that was being made, and tells the gate `cancelled`
- a finished run reports to the gate that the action is complete, a failed one `failed`
- a grading run saves the card on the attempt; one that cannot finish marks the attempt failed so it can be graded again
- the quiz's runs are found through the quiz, whoever started them
"""

import contextlib

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from support.fakes import FakeSandbox
from support.fixtures import budget_snapshot
from support.gates import CountingGate
from support.lesson_data import make_final_test
from support.question_data import ScriptedQuestions
from support.quiz_data import make_questions

from graph.context import FlowContext
from graph.quiz_config import QuizConfig
from graph.registry import GraphRegistry
from graph.schemas import DiagnosticBundle
from lessons.effects import RunEffects
from lessons.events import RunEvent
from lessons.metering import ActionContext, Authorization, AuthorizationSettlement, CompletionPoints, MeteredAction
from lessons.models import GraphRun
from lessons.runner import FlowRunner
from lessons.services import LessonService
from llm_registry.gateway import AllModelsFailed
from quizzes.models import QuickQuiz, QuickQuizAttempt
from quizzes.stages import QuizStage

pytestmark = pytest.mark.django_db(transaction=True)


class ListPublisher:
    def __init__(self):
        self.published: list[tuple[str, RunEvent]] = []

    def publish(self, run_id, event):
        self.published.append((str(run_id), event))

    def of(self, name):
        return [event.data for _, event in self.published if event.name == name]


class SharedMemory:
    def __init__(self):
        self._saver = InMemorySaver()

    @contextlib.contextmanager
    def saver(self):
        yield self._saver


@pytest.fixture
def gate():
    return CountingGate()


@pytest.fixture
def publisher():
    return ListPublisher()


@pytest.fixture
def runner(gateway, publisher, gate):
    checkpoints = SharedMemory()

    def context(run_id):
        return FlowContext(gateway=gateway, sandbox=FakeSandbox(), run_id=run_id)

    return FlowRunner(
        graphs=GraphRegistry(), checkpointers=checkpoints, events=publisher, context_factory=context,
        effects=RunEffects(settlement=AuthorizationSettlement(gate)),
    )  # fmt: skip


@pytest.fixture
def questions(gateway):
    gateway.respond("test.generate", ScriptedQuestions())


@pytest.fixture
def made(make_quiz, flow_settings, make_attempt, gate):
    """A quiz as the service leaves it, its waiting attempt, and the start run that holds a counted authorization."""

    def _made(*, mode="self_rating", stage=QuizStage.PREPARING, **fields):
        config = QuizConfig(10, ("mcq",), mode, 6 if mode == "self_rating" else None)
        quiz = make_quiz(
            config=config, stage=stage, config_snapshot=budget_snapshot(), settings_snapshot=flow_settings, **fields
        )
        attempt = make_attempt(quiz, status="generating", questions=[])
        context = ActionContext(
            quiz.owner,
            MeteredAction.QUIZ_CREATE,
            {},
            quiz.id,
            "k",
            False,
            CompletionPoints.of(MeteredAction.QUIZ_CREATE),
        )
        authorization = Authorization.of(context)
        run = GraphRun.objects.create(
            quick_quiz=quiz, graph=GraphRun.Graph.QUICK_QUIZ, trigger=GraphRun.Trigger.START,
            payload={"input": {"attempt_id": str(attempt.id)}, "authorization": authorization.to_payload()},
        )  # fmt: skip
        return quiz, attempt, run

    return _made


class TestTheThreads:
    def test_the_first_run_and_the_calibration_resume_share_the_quizs_thread(self, quiz):
        start = GraphRun(quick_quiz=quiz, graph="quick_quiz", trigger=GraphRun.Trigger.START)
        resume = GraphRun(quick_quiz=quiz, graph="quick_quiz", trigger=GraphRun.Trigger.RESUME_CALIBRATION)

        assert FlowRunner.thread_id(start) == FlowRunner.thread_id(resume) == str(quiz.id)

    @pytest.mark.parametrize(
        ("graph", "trigger"),
        [("quick_quiz", GraphRun.Trigger.RETAKE), ("grade_quiz", GraphRun.Trigger.GRADE)],
    )
    def test_a_retake_and_a_grading_run_have_a_thread_of_their_own(self, quiz, graph, trigger):
        run = GraphRun(quick_quiz=quiz, graph=graph, trigger=trigger)

        assert FlowRunner.thread_id(run) == f"{quiz.id}:{run.id}"


class TestARatedQuiz:
    def test_the_run_streams_to_the_end_and_the_quiz_is_ready(self, runner, made, questions, publisher, gate):
        quiz, attempt, run = made()

        done = runner.execute(run.id)

        assert done.status == GraphRun.Status.SUCCEEDED
        assert QuickQuizAttempt.objects.get(pk=attempt.pk).status == "in_progress"
        assert QuickQuiz.objects.get(pk=quiz.pk).stage == QuizStage.READY
        assert publisher.of("done") == [{"quiz_id": str(quiz.id), "stage": "ready"}]
        assert "level_from_rating" in done.node_status

    def test_the_gate_is_told_the_action_is_complete(self, runner, made, questions, gate):
        _, _, run = made()

        runner.execute(run.id)

        assert gate.settled == [("quiz.create", "succeeded")]


class TestTheCalibrationWalk:
    @pytest.fixture
    def paused(self, runner, made, questions, gateway):
        gateway.script(
            "diagnostic.generate",
            DiagnosticBundle(diagnostic=make_questions(), prerequisites=[], prerequisite_questions=[]).model_dump(),
        )
        quiz, attempt, run = made(mode="calibration")
        return quiz, attempt, runner.execute(run.id)

    def test_the_start_run_pauses_for_the_walk(self, paused, publisher):
        quiz, attempt, run = paused

        assert run.status == GraphRun.Status.PAUSED
        assert publisher.of("awaiting_input") == [{"kind": "calibration", "quiz_id": str(quiz.id)}]
        assert QuickQuiz.objects.get(pk=quiz.pk).stage == QuizStage.AWAITING_CALIBRATION

    def test_the_pause_is_not_a_settlement(self, paused, gate):
        assert gate.settled == []

    def test_the_resume_continues_the_same_thread_to_the_end(self, paused, runner):
        quiz, attempt, _ = paused
        QuickQuiz.objects.filter(pk=quiz.pk).update(
            calibration={"pool": [], "walk": [{"question_id": "q", "band": "b", "correct": True}] * 5}
        )
        authorization = GraphRun.objects.get(quick_quiz=quiz).payload["authorization"]
        resume = GraphRun.objects.create(
            quick_quiz=quiz, graph="quick_quiz", trigger=GraphRun.Trigger.RESUME_CALIBRATION,
            payload={"resume": True, "authorization": authorization},
        )  # fmt: skip

        done = runner.execute(resume.id)

        assert done.status == GraphRun.Status.SUCCEEDED
        assert QuickQuiz.objects.get(pk=quiz.pk).stage == QuizStage.READY
        assert QuickQuizAttempt.objects.get(pk=attempt.pk).status == "in_progress"


class TestAFailure:
    def broken(self, gateway):
        gateway.respond("test.generate", AllModelsFailed("test.generate", ["fake: boom"]))

    def test_a_quiz_being_made_is_failed_and_its_waiting_attempt_goes(self, runner, made, gateway, publisher, gate):
        self.broken(gateway)
        quiz, attempt, run = made()

        done = runner.execute(run.id)

        assert done.status == GraphRun.Status.FAILED and "test.generate" in done.error
        stored = QuickQuiz.objects.get(pk=quiz.pk)
        assert stored.stage == QuizStage.FAILED and "test.generate" in stored.error
        assert not QuickQuizAttempt.objects.filter(pk=attempt.pk).exists()
        assert gate.settled == [("quiz.create", "failed")]

    def test_a_retake_that_fails_leaves_the_quiz_ready_and_the_old_attempts_alone(
        self, runner, made, gateway, make_attempt, gate
    ):
        self.broken(gateway)
        quiz, waiting, _ = made(stage=QuizStage.READY, assessment={"level": "foundation", "level_scheme": 2})
        QuickQuizAttempt.objects.filter(pk=waiting.pk).update(status="graded")
        retaking = make_attempt(quiz, status="generating", questions=[])
        run = GraphRun.objects.create(
            quick_quiz=quiz, graph="quick_quiz", trigger=GraphRun.Trigger.RETAKE,
            payload={"input": {"attempt_id": str(retaking.pk)}},
        )  # fmt: skip

        runner.execute(run.id)

        assert QuickQuiz.objects.get(pk=quiz.pk).stage == QuizStage.READY
        assert list(quiz.attempts.values_list("attempt_no", flat=True)) == [1]

    def test_a_quiz_that_was_deleted_meanwhile_fails_the_run_without_a_crash(self, runner, made, questions):
        quiz, attempt, run = made()
        QuickQuizAttempt.objects.filter(pk=attempt.pk).delete()

        done = runner.execute(run.id)

        assert done.status == GraphRun.Status.FAILED and "cancelled" in done.error


class TestStopping:
    def test_stopping_removes_the_waiting_attempt_fails_the_quiz_and_tells_the_gate(self, made, gate, publisher):
        quiz, attempt, run = made()
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)
        run.refresh_from_db()

        LessonService(gate=gate, events=publisher).cancel(run)

        assert not QuickQuizAttempt.objects.filter(pk=attempt.pk).exists()
        assert QuickQuiz.objects.get(pk=quiz.pk).stage == QuizStage.FAILED
        assert gate.settled == [("quiz.create", "cancelled")]
        assert publisher.of("cancelled") == [{}]


class TestGrading:
    @pytest.fixture
    def grading(self, quiz, make_attempt, flow_settings):
        test = make_final_test()
        QuickQuiz.objects.filter(pk=quiz.pk).update(config_snapshot=budget_snapshot(), settings_snapshot=flow_settings)
        answers = {
            q["id"]: ("Halve the range." if q["type"] in ("short_answer", "long_answer") else 0)
            for q in test["questions"]
        }
        attempt = make_attempt(quiz, status="grading", questions=test["questions"], answers=answers)
        run = GraphRun.objects.create(
            quick_quiz=quiz, graph=GraphRun.Graph.GRADE_QUIZ, trigger=GraphRun.Trigger.GRADE,
            payload={"input": {"attempt_id": str(attempt.pk)}},
        )  # fmt: skip
        return attempt, run

    def test_the_card_is_saved_on_the_attempt(self, runner, grading, gateway):
        attempt, run = grading
        gateway.respond(
            "test.grade",
            lambda messages: {"grades": [
                {"question_id": q["id"], "awards": [c["marks"] for c in q["criteria"]], "feedback": "Good."}
                for q in make_final_test()["questions"] if q["type"] in ("short_answer", "long_answer")
            ]},
        )  # fmt: skip

        done = runner.execute(run.id)

        assert done.status == GraphRun.Status.SUCCEEDED
        assert QuickQuizAttempt.objects.get(pk=attempt.pk).status == "graded"

    def test_a_grading_that_cannot_finish_marks_the_attempt_failed_so_it_can_be_graded_again(
        self, runner, grading, gateway
    ):
        attempt, run = grading
        gateway.respond("test.grade", AllModelsFailed("test.grade", ["boom"]))

        done = runner.execute(run.id)

        assert done.status == GraphRun.Status.FAILED
        stored = QuickQuizAttempt.objects.get(pk=attempt.pk)
        assert stored.status == "failed" and "test.grade" in stored.error

    def test_a_failed_grading_does_not_fail_the_quiz(self, runner, grading, gateway):
        attempt, run = grading
        gateway.respond("test.grade", AllModelsFailed("test.grade", ["boom"]))

        runner.execute(run.id)

        assert QuickQuiz.objects.get(pk=attempt.quiz_id).stage == QuizStage.READY


def test_the_runs_of_a_quiz_are_found_through_the_quiz(made):
    quiz, _, run = made()

    assert list(GraphRun.objects.for_subject(quiz)) == [run]

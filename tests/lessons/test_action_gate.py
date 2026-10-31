"""Unit under test: the action gate as the lesson services use it (`LessonService`, `QuizService`, `MaterialService`,
`RunEffects.on_finished`/`on_stopped` through `AuthorizationSettlement`, and the `Idempotency-Key` header on the views).

Why: this is where a later pricing feature would be told "this learner is about to start paid work". It has to be asked
exactly once, before anything exists, and told how the work ended. A refusal that still creates a lesson, a Retry that
asks nothing (free work after a Stop) or twice (a double charge), an abandoned diagnostic that reaches
`lesson.continue`, or a replayed request that authorizes again would each be a real bug the day metering switches on.

Use cases:
- starting a lesson asks `lesson.create` once, with the new lesson's id as subject, stores the authorization on the run,
  and a refusal creates no lesson and no run and queues nothing
- a lesson that cannot be started because no model is bound never asks
- a queue that is unreachable releases the authorization as failed
- the quiz being served settles `lesson.create` as succeeded, once, even if told twice; a lesson not yet there does not
- a diagnostic that is never answered never reaches `lesson.continue`
- submitting a diagnostic that is not perfect asks `lesson.continue` once, after grading and before the attempt is
  stored, and a refusal stores no attempt and queues no run; nothing is asked when the answers are invalid, the quiz was
  answered, the stage is wrong or a run is active
- a perfect diagnostic asks nothing at submit; the choice asks `lesson.continue` (perfect, sheets only), a refusal there
  creates no run, and nothing is asked when the stage is wrong
- the prerequisite quiz does not ask again: it carries the open authorization, which settles when the lesson is ready
- a pause before the completion point is not a settlement
- a failed run settles failed; Stop settles cancelled; neither settles twice
- Stop then Retry asks exactly once, with `resume`, for the same action and size; a refused Retry leaves the lesson
  failed and creates no run; a Retry of work that was kept asks nothing
- an extra sheet asks `sheet.generate` once (the number of sheets, and what they rest on: the lesson, the quiz or
  nothing but the topic); a refusal creates no run; a sheet that exists, a wrong stage or a run in progress never ask;
  the run ending settles it
- a lesson that asks for sheets asks `lesson.create` with the intent, the number of sheets and what they rest on; its
  quick check asks `lesson.continue` once at submit, with `sheets_only` whatever the score and whether it was perfect,
  and
  shows no route; a self-rated one asks nothing more after the one `lesson.create` that covers all
- deleting a lesson settles an open authorization as cancelled and leaves a settled one alone
- with the open gate nothing is stored on the run
- a replayed `Idempotency-Key` on starting a lesson or asking for a sheet returns the first answer and authorizes once
- a refusal reaches the API as an error body with its code
"""

import pytest
from support.gates import CountingGate, RefusingGate, SharedCountingGate
from support.quiz_data import make_prerequisites, make_questions
from support.study_data import make_cheat_sheet

from lessons.effects import RunEffects
from lessons.errors import AlreadyAttempted, AlreadyExists, InvalidAnswers, QueueUnavailable, RunInProgress, WrongStage
from lessons.metering import ActionRefused, AuthorizationSettlement, MeteredAction, RunOutcome
from lessons.models import GraphRun, Lesson, Quiz, QuizAttempt, Stage, StudyMaterial
from lessons.services import LessonService, MaterialService, QuizService

pytestmark = pytest.mark.django_db

LESSON_CREATE = MeteredAction.LESSON_CREATE
LESSON_CONTINUE = MeteredAction.LESSON_CONTINUE
SHEET_GENERATE = MeteredAction.SHEET_GENERATE


class Silent:
    def publish(self, run_id, event):
        pass


def settlement(gate):
    return RunEffects(settlement=AuthorizationSettlement(gate))


def lessons(gate, queue):
    return LessonService(queue=queue, events=Silent(), gate=gate)


def make_quiz(lesson, kind="diagnostic"):
    questions = make_questions() if kind == "diagnostic" else make_prerequisites()[1]
    quiz = Quiz.objects.create(lesson=lesson, kind=kind, questions=questions)
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage(f"awaiting_{kind}"), settings_snapshot={"prereq_trigger_max_correct": 2}
    )
    lesson.refresh_from_db()
    return quiz


def answers_for(quiz, right):
    return {
        q["id"]: q["correct_index"] if n < right else (q["correct_index"] + 1) % 4 for n, q in enumerate(quiz.questions)
    }


def paused(run, stage, lesson):
    """The run reached a pause with the lesson at `stage`, as the runner leaves it."""
    GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.PAUSED)
    Lesson.objects.filter(pk=lesson.pk).update(stage=stage)
    run.refresh_from_db()
    return run


class TestStartingALesson:
    def test_asks_lesson_create_once_for_the_new_lesson_and_stores_it_on_the_run(self, user, queue, bound_registry):
        gate = CountingGate()

        lesson, run = lessons(gate, queue).create(user, "Binary search")

        (asked,) = gate.authorized
        assert (asked.action, asked.user, asked.resume) == (LESSON_CREATE, user, False)
        assert asked.subject_id == lesson.id
        assert asked.size == {"entry": "diagnostic", "intent": "lesson", "covers": "diagnostic", "origin": "direct"}
        assert run.payload["authorization"]["action"] == "lesson.create"
        assert run.payload["authorization"].get("settled") is None

    def test_a_refusal_creates_no_lesson_and_no_run_and_queues_nothing(self, user, queue, bound_registry):
        gate = RefusingGate()

        with pytest.raises(ActionRefused):
            lessons(gate, queue).create(user, "Binary search")

        assert Lesson.objects.count() == 0 and GraphRun.objects.count() == 0 and queue.runs == []

    def test_a_lesson_that_cannot_be_started_never_asks(self, user, queue, db):
        from llm_registry.node_configs import NodeConfigSync

        NodeConfigSync().ensure()
        gate = CountingGate()

        with pytest.raises(Exception, match="diagnostic.generate"):
            lessons(gate, queue).create(user, "Binary search")

        assert gate.authorized == []

    def test_the_clients_idempotency_key_reaches_the_gate(self, user, queue, bound_registry):
        gate = CountingGate()

        lesson, _ = lessons(gate, queue).create(user, "Binary search", idempotency_key="abc")

        assert gate.authorized[0].key == f"lesson.create:{lesson.id}:abc"

    def test_an_unreachable_queue_releases_the_authorization_as_failed(self, user, bound_registry):
        class Broken:
            def enqueue(self, run):
                raise QueueUnavailable()

        gate = CountingGate()

        with pytest.raises(QueueUnavailable):
            LessonService(queue=Broken(), events=Silent(), gate=gate).create(user, "Binary search")

        assert gate.settled == [("lesson.create", RunOutcome.FAILED)]

    def test_with_the_open_gate_nothing_is_stored_on_the_run(self, user, queue, bound_registry):
        _, run = LessonService(queue=queue, events=Silent()).create(user, "Binary search")

        assert run.payload == {}


class TestSettlingTheFirstStage:
    def started(self, user, queue, gate):
        lesson, run = lessons(gate, queue).create(user, "Binary search")
        return lesson, run

    def test_the_quiz_being_served_settles_lesson_create_as_succeeded_once(self, user, queue, bound_registry):
        gate = CountingGate()
        lesson, run = self.started(user, queue, gate)
        run = paused(run, Stage.AWAITING_DIAGNOSTIC, lesson)

        settlement(gate).on_finished(run)
        settlement(gate).on_finished(run)  # a redelivered task tells it again

        assert gate.settled == [("lesson.create", RunOutcome.SUCCEEDED)]

    def test_a_lesson_not_yet_at_the_quiz_is_not_settled(self, user, queue, bound_registry):
        gate = CountingGate()
        lesson, run = self.started(user, queue, gate)
        run = paused(run, Stage.PREPARING_DIAGNOSTIC, lesson)

        settlement(gate).on_finished(run)

        assert gate.settled == []

    def test_a_diagnostic_that_is_never_answered_never_reaches_lesson_continue(self, user, queue, bound_registry):
        gate = CountingGate()
        lesson, run = self.started(user, queue, gate)
        paused(run, Stage.AWAITING_DIAGNOSTIC, lesson)
        settlement(gate).on_finished(run)

        assert gate.actions == ["lesson.create"]
        assert gate.settled == [("lesson.create", RunOutcome.SUCCEEDED)]


class TestSubmittingTheDiagnostic:
    def test_a_diagnostic_that_is_not_perfect_asks_lesson_continue_once_and_stores_it_on_the_resume_run(
        self, lesson, queue
    ):
        quiz = make_quiz(lesson)
        gate = CountingGate()

        _, run = QuizService(queue=queue, gate=gate).submit(lesson, "diagnostic", answers_for(quiz, 6))

        (asked,) = gate.authorized
        assert (asked.action, asked.subject_id, asked.resume) == (LESSON_CONTINUE, lesson.id, False)
        assert asked.size == {"choice": "lesson", "perfect": False}
        assert run.payload["authorization"]["action"] == "lesson.continue"
        assert run.payload["resume"] == str(QuizAttempt.objects.get(quiz=quiz).id)

    def test_a_refusal_stores_no_attempt_and_queues_no_run(self, lesson, queue):
        quiz = make_quiz(lesson)

        with pytest.raises(ActionRefused):
            QuizService(queue=queue, gate=RefusingGate()).submit(lesson, "diagnostic", answers_for(quiz, 6))

        assert QuizAttempt.objects.count() == 0 and GraphRun.objects.count() == 0 and queue.runs == []
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_DIAGNOSTIC  # the learner can resubmit

    def test_the_gate_is_asked_after_the_answers_are_graded_and_checked(self, lesson, queue):
        quiz = make_quiz(lesson)
        gate = CountingGate()
        service = QuizService(queue=queue, gate=gate)

        with pytest.raises(InvalidAnswers):
            service.submit(lesson, "diagnostic", {"q1": 99})
        with pytest.raises(InvalidAnswers):
            service.submit(lesson, "diagnostic", ["not", "a", "dict"])

        assert gate.authorized == [] and QuizAttempt.objects.count() == 0
        service.submit(lesson, "diagnostic", answers_for(quiz, 6))
        assert len(gate.authorized) == 1

    def test_an_answered_quiz_a_wrong_stage_or_an_active_run_never_ask(self, lesson, queue):
        quiz = make_quiz(lesson)
        gate = CountingGate()
        service = QuizService(queue=queue, gate=gate)
        service.submit(lesson, "diagnostic", answers_for(quiz, 6))
        gate.authorized.clear()

        with pytest.raises(AlreadyAttempted):
            service.submit(lesson, "diagnostic", answers_for(quiz, 6))

        elsewhere = Lesson.objects.create(owner=lesson.owner, topic="Elsewhere")
        wrong_stage_quiz = make_quiz(elsewhere)
        Lesson.objects.filter(pk=elsewhere.pk).update(stage=Stage.READY)
        with pytest.raises(WrongStage):
            service.submit(elsewhere, "diagnostic", answers_for(wrong_stage_quiz, 6))

        other = Lesson.objects.create(owner=lesson.owner, topic="Other")
        make_quiz(other)
        GraphRun.objects.create(lesson=other, trigger=GraphRun.Trigger.START, status=GraphRun.Status.RUNNING)
        with pytest.raises(RunInProgress):
            service.submit(other, "diagnostic", answers_for(Quiz.objects.get(lesson=other), 6))

        assert gate.authorized == []

    def test_a_perfect_diagnostic_asks_nothing_at_submit(self, lesson, queue):
        quiz = make_quiz(lesson)
        gate = CountingGate()

        summary, run = QuizService(queue=queue, gate=gate).submit(lesson, "diagnostic", answers_for(quiz, 10))

        assert summary["route"] == "mastery"
        assert gate.authorized == [] and "authorization" not in run.payload

    def test_the_prerequisite_route_asks_lesson_continue_at_the_diagnostic(self, lesson, queue):
        quiz = make_quiz(lesson)
        gate = CountingGate()

        summary, _ = QuizService(queue=queue, gate=gate).submit(lesson, "diagnostic", answers_for(quiz, 1))

        assert summary["route"] == "prerequisite" and gate.actions == ["lesson.continue"]


class TestThePrerequisiteStage:
    def test_the_prerequisite_quiz_carries_the_open_authorization_instead_of_asking_again(self, lesson, queue):
        quiz = make_quiz(lesson)
        gate = CountingGate()
        service = QuizService(queue=queue, gate=gate)
        _, first = service.submit(lesson, "diagnostic", answers_for(quiz, 1))

        first = paused(first, Stage.AWAITING_PREREQUISITE, lesson)
        settlement(gate).on_finished(first)  # a pause before the completion point is not a settlement
        assert gate.settled == []
        prerequisite = Quiz.objects.create(
            lesson=lesson, kind="prerequisite", questions=make_prerequisites()[1], prerequisites=[]
        )

        _, second = service.submit(lesson, "prerequisite", answers_for(prerequisite, 3))

        assert len(gate.authorized) == 1
        assert second.payload["authorization"]["id"] == first.payload["authorization"]["id"]
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)
        second.refresh_from_db()
        settlement(gate).on_finished(second, ended=True)
        settlement(gate).on_finished(second, ended=True)
        assert gate.settled == [("lesson.continue", RunOutcome.SUCCEEDED)]


class TestTheMasteryChoice:
    def mastery(self, make_lesson):
        return make_lesson(stage=Stage.AWAITING_CHOICE, route="mastery")

    @pytest.mark.parametrize(("choice", "size"), [
        ("lesson", {"choice": "lesson", "perfect": True}),
        ("sheets", {"choice": "sheets_only", "perfect": True, "sheets": 2, "grounding": "quiz"}),
        ("cheat_sheet", {"choice": "sheets_only", "perfect": True, "sheets": 1, "grounding": "quiz"}),
    ])  # fmt: skip
    def test_the_choice_asks_lesson_continue_for_a_perfect_score_with_what_was_chosen(
        self, make_lesson, queue, choice, size
    ):
        lesson = self.mastery(make_lesson)
        gate = CountingGate()

        run = MaterialService(queue=queue, gate=gate).choose(lesson, choice)

        (asked,) = gate.authorized
        assert (asked.action, asked.subject_id) == (LESSON_CONTINUE, lesson.id)
        assert asked.size == size
        assert run.payload["authorization"]["action"] == "lesson.continue"

    def test_a_refusal_creates_no_run(self, make_lesson, queue):
        with pytest.raises(ActionRefused):
            MaterialService(queue=queue, gate=RefusingGate()).choose(self.mastery(make_lesson), "cheat_sheet")

        assert GraphRun.objects.count() == 0 and queue.runs == []

    @pytest.mark.parametrize("stage", [Stage.AWAITING_DIAGNOSTIC, Stage.READY])
    def test_the_wrong_stage_never_asks(self, make_lesson, queue, stage):
        gate = CountingGate()

        with pytest.raises(WrongStage):
            MaterialService(queue=queue, gate=gate).choose(make_lesson(stage=stage, route="mastery"), "cheat_sheet")

        assert gate.authorized == []


class TestFailureStopAndRetry:
    def failed_lesson(self, user, queue, gate):
        lesson, run = lessons(gate, queue).create(user, "Binary search")
        return lesson, run

    def test_a_failed_run_settles_failed_and_a_run_that_was_stopped_settles_cancelled_once(
        self, user, queue, bound_registry
    ):
        gate = CountingGate()
        lesson, run = self.failed_lesson(user, queue, gate)
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)
        run.refresh_from_db()

        lessons(gate, queue).cancel(run)  # Stop
        settlement(gate).on_stopped(run, "Cancelled before it finished.")  # the runner finds out later

        assert gate.settled == [("lesson.create", RunOutcome.CANCELLED)]

    def test_a_backend_failure_settles_failed(self, user, queue, bound_registry):
        gate = CountingGate()
        lesson, run = self.failed_lesson(user, queue, gate)
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)
        run.refresh_from_db()

        settlement(gate).on_stopped(run, "Every AI model failed.")  # before the runner marks the run failed

        assert gate.settled == [("lesson.create", RunOutcome.FAILED)]

    def test_stop_then_retry_asks_exactly_once_with_resume_for_the_same_action(self, user, queue, bound_registry):
        gate = CountingGate()
        service = lessons(gate, queue)
        lesson, run = self.failed_lesson(user, queue, gate)
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)
        run.refresh_from_db()
        service.cancel(run)
        lesson.refresh_from_db()

        retry = service.retry(lesson)

        assert gate.settled == [("lesson.create", RunOutcome.CANCELLED)]
        assert len(gate.authorized) == 2
        again = gate.authorized[1]
        assert (again.action, again.resume, again.subject_id) == (LESSON_CREATE, True, lesson.id)
        assert again.size == gate.authorized[0].size
        assert retry.payload["authorization"]["resume"] is True

    def test_a_refused_retry_leaves_the_lesson_failed_and_creates_no_run(self, user, queue, bound_registry):
        gate = CountingGate()
        lesson, run = self.failed_lesson(user, queue, gate)
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)
        run.refresh_from_db()
        lessons(gate, queue).cancel(run)
        lesson.refresh_from_db()
        runs_before, queued_before = GraphRun.objects.count(), len(queue.runs)

        with pytest.raises(ActionRefused):
            lessons(RefusingGate(), queue).retry(lesson)

        lesson.refresh_from_db()
        assert lesson.stage == Stage.FAILED
        assert GraphRun.objects.count() == runs_before and len(queue.runs) == queued_before

    def test_a_retry_of_work_that_was_kept_asks_nothing(self, user, queue, bound_registry):
        gate = CountingGate()
        lesson, run = self.failed_lesson(user, queue, gate)
        run = paused(run, Stage.AWAITING_DIAGNOSTIC, lesson)
        settlement(gate).on_finished(run)  # the quiz was served: kept
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED, error="boom")
        lesson.refresh_from_db()
        asked_before = len(gate.authorized)

        lessons(gate, queue).retry(lesson)

        assert len(gate.authorized) == asked_before

    def test_with_the_open_gate_a_retry_stores_nothing(self, make_lesson, queue):
        lesson = make_lesson(stage=Stage.FAILED, error="boom")

        run = LessonService(queue=queue, events=Silent()).retry(lesson)

        assert run.payload == {}


class TestRequestingAnExtraSheet:
    def ready(self, make_lesson):
        return make_lesson(stage=Stage.READY, route="mastery")

    def test_asks_sheet_generate_once_for_one_sheet_grounded_on_the_quiz(self, make_lesson, queue):
        lesson = self.ready(make_lesson)
        gate = CountingGate()

        run = MaterialService(queue=queue, gate=gate).request_extra(lesson, "revision_sheet", idempotency_key="k")

        (asked,) = gate.authorized
        assert (asked.action, asked.subject_id) == (SHEET_GENERATE, lesson.id)
        assert asked.size == {"sheets": 1, "grounding": "quiz"}
        assert asked.key.endswith(":k")
        assert run.payload["input"] == {"sheet_kinds": ["revision_sheet"], "extra_material": True}
        assert run.payload["authorization"]["action"] == "sheet.generate"

    @pytest.mark.parametrize(("kinds", "count"), [("cheat_sheet", 1), (["cheat_sheet", "revision_sheet"], 2)])
    def test_the_gate_is_asked_once_whatever_the_number_of_sheets_and_told_how_many(
        self, make_lesson, queue, kinds, count
    ):
        gate = CountingGate()

        MaterialService(queue=queue, gate=gate).request_extra(self.ready(make_lesson), kinds)

        assert len(gate.authorized) == 1 and gate.authorized[0].size["sheets"] == count

    @pytest.mark.parametrize(("fields", "grounding"), [
        ({"plan": {"x": 1}, "pages": {"core": {}}, "route": "lesson"}, "lesson"),
        ({"route": "mastery"}, "quiz"),
        ({"intent": "sheets"}, "quiz"),
        ({"intent": "sheets", "entry": "self_rating", "self_rating_halves": 5}, "none"),
    ])  # fmt: skip
    def test_the_sheets_rest_on_the_lesson_the_quiz_or_nothing_but_the_topic(
        self, make_lesson, queue, fields, grounding
    ):
        gate = CountingGate()

        MaterialService(queue=queue, gate=gate).request_extra(make_lesson(stage=Stage.READY, **fields), "cheat_sheet")

        assert gate.authorized[0].size["grounding"] == grounding

    def test_a_refusal_creates_no_run(self, make_lesson, queue):
        with pytest.raises(ActionRefused):
            MaterialService(queue=queue, gate=RefusingGate()).request_extra(self.ready(make_lesson), "cheat_sheet")

        assert GraphRun.objects.count() == 0 and queue.runs == []

    def test_a_sheet_that_exists_a_wrong_stage_or_a_run_in_progress_never_ask(self, make_lesson, queue):
        lesson = self.ready(make_lesson)
        StudyMaterial.objects.create(lesson=lesson, kind="cheat_sheet", content=make_cheat_sheet())
        gate = CountingGate()
        service = MaterialService(queue=queue, gate=gate)

        with pytest.raises(AlreadyExists):
            service.request_extra(lesson, "cheat_sheet")
        with pytest.raises(WrongStage):
            service.request_extra(make_lesson(stage=Stage.GENERATING_LESSON, route="lesson"), "cheat_sheet")
        GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.RUNNING)
        with pytest.raises(RunInProgress):
            service.request_extra(lesson, "revision_sheet")

        assert gate.authorized == []

    def test_the_run_ending_settles_it_as_succeeded_and_a_failure_as_failed(self, make_lesson, queue):
        lesson = self.ready(make_lesson)
        gate = CountingGate()
        run = MaterialService(queue=queue, gate=gate).request_extra(lesson, "revision_sheet")

        settlement(gate).on_finished(run, ended=False)
        assert gate.settled == []  # not ended: not complete
        settlement(gate).on_finished(run, ended=True)
        assert gate.settled == [("sheet.generate", RunOutcome.SUCCEEDED)]
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.SUCCEEDED)

        other = MaterialService(queue=queue, gate=gate).request_extra(lesson, "cheat_sheet")
        settlement(gate).on_stopped(other, "boom")
        assert gate.settled[-1] == ("sheet.generate", RunOutcome.FAILED)


class TestASheetsLesson:
    def waiting(self, make_lesson, kinds=("cheat_sheet", "revision_sheet"), **fields):
        lesson = make_lesson(intent="sheets", **fields)
        GraphRun.objects.create(
            lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.PAUSED,
            payload={"input": {"sheet_kinds": list(kinds)}},
        )  # fmt: skip
        return lesson, make_quiz(lesson)

    @pytest.mark.parametrize(("right", "perfect"), [(1, False), (6, False), (10, True)])
    def test_the_quick_check_asks_lesson_continue_once_with_sheets_only_whatever_the_score(
        self, make_lesson, queue, right, perfect
    ):
        lesson, quiz = self.waiting(make_lesson)
        gate = CountingGate()

        summary, run = QuizService(queue=queue, gate=gate).submit(lesson, "diagnostic", answers_for(quiz, right))

        (asked,) = gate.authorized
        assert asked.action == LESSON_CONTINUE and asked.subject_id == lesson.id
        assert asked.size == {
            "choice": "sheets_only", "perfect": perfect, "intent": "sheets", "sheets": 2, "grounding": "quiz",
        }  # fmt: skip
        assert asked.completes_at.to_payload() == {"kind": "stage", "stage": "ready"}
        assert run.payload["authorization"]["action"] == "lesson.continue"
        assert "route" not in summary and summary["correct"] == right  # it is neither kind of lesson

    def test_it_counts_the_sheets_that_were_asked_for(self, make_lesson, queue):
        lesson, quiz = self.waiting(make_lesson, kinds=("revision_sheet",))
        gate = CountingGate()

        QuizService(queue=queue, gate=gate).submit(lesson, "diagnostic", answers_for(quiz, 5))

        assert gate.authorized[0].size["sheets"] == 1

    def test_a_refusal_at_submit_stores_no_attempt_and_queues_no_run(self, make_lesson, queue):
        lesson, quiz = self.waiting(make_lesson)

        with pytest.raises(ActionRefused):
            QuizService(queue=queue, gate=RefusingGate()).submit(lesson, "diagnostic", answers_for(quiz, 10))

        assert QuizAttempt.objects.count() == 0 and queue.runs == []

    def test_a_lesson_made_by_a_mastery_choice_is_not_asked_again_at_submit(self, make_lesson, queue):
        lesson = make_lesson()
        quiz = make_quiz(lesson)
        gate = CountingGate()

        QuizService(queue=queue, gate=gate).submit(lesson, "diagnostic", answers_for(quiz, 10))

        assert gate.authorized == []  # the perfect score of a lesson that asked for a lesson still waits for its choice


class TestDeletingALesson:
    def test_settles_an_open_authorization_as_cancelled(self, make_lesson, queue):
        lesson = make_lesson(stage=Stage.READY, route="mastery")
        gate = CountingGate()
        MaterialService(queue=queue, gate=gate).request_extra(lesson, "revision_sheet")

        LessonService(queue=queue, events=Silent(), gate=gate).delete(lesson)

        assert gate.settled == [("sheet.generate", RunOutcome.CANCELLED)]

    def test_leaves_a_settled_authorization_alone(self, user, queue, bound_registry):
        gate = CountingGate()
        lesson, run = lessons(gate, queue).create(user, "Binary search")
        run = paused(run, Stage.AWAITING_DIAGNOSTIC, lesson)
        settlement(gate).on_finished(run)

        lessons(gate, queue).delete(lesson)

        assert gate.settled == [("lesson.create", RunOutcome.SUCCEEDED)]


@pytest.fixture
def shared_gate(settings):
    SharedCountingGate.reset()
    settings.ACTION_GATE = "support.gates.SharedCountingGate"
    return SharedCountingGate


class TestIdempotencyKeyOnTheViews:
    def start(self, client, key=None, topic="Binary search"):
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
        return client.post("/api/lessons", {"topic": topic}, format="json", **headers)

    def test_a_replayed_key_returns_the_first_answer_and_authorizes_once(
        self, signed_in_client, queue, bound_registry, shared_gate
    ):
        first = self.start(signed_in_client, "key-1")
        second = self.start(signed_in_client, "key-1")

        assert first.status_code == second.status_code == 202
        assert second.json() == first.json() and second["Idempotent-Replayed"] == "true"
        assert Lesson.objects.count() == 1 and len(queue.runs) == 1
        assert len(shared_gate.authorized) == 1

    def test_a_different_key_or_no_key_starts_another_lesson(
        self, signed_in_client, queue, bound_registry, shared_gate
    ):
        self.start(signed_in_client, "key-1")
        self.start(signed_in_client, "key-2")
        self.start(signed_in_client)

        assert Lesson.objects.count() == 3 and len(shared_gate.authorized) == 3

    def test_a_bad_key_is_a_400_and_starts_nothing(self, signed_in_client, queue, bound_registry, shared_gate):
        response = self.start(signed_in_client, "has space")

        assert response.status_code == 400 and response.json()["code"] == "invalid_idempotency_key"
        assert Lesson.objects.count() == 0

    def test_a_replayed_key_on_a_sheet_request_authorizes_once(self, signed_in_client, make_lesson, queue, shared_gate):
        lesson = make_lesson(stage=Stage.READY, route="mastery")
        url = f"/api/lessons/{lesson.id}/materials"

        first = signed_in_client.post(url, {"kind": "cheat_sheet"}, format="json", HTTP_IDEMPOTENCY_KEY="s-1")
        second = signed_in_client.post(url, {"kind": "cheat_sheet"}, format="json", HTTP_IDEMPOTENCY_KEY="s-1")

        assert first.status_code == second.status_code == 202 and second.json() == first.json()
        assert GraphRun.objects.filter(lesson=lesson).count() == 1 and len(shared_gate.authorized) == 1

    def test_a_refusal_reaches_the_api_as_an_error_with_its_code(
        self, signed_in_client, queue, bound_registry, settings
    ):
        settings.ACTION_GATE = "support.gates.RefusingGate"

        response = self.start(signed_in_client, "key-9")

        assert response.status_code == 403
        assert response.json()["code"] == "test_refused" and response.json()["detail"] == "Not available."
        assert Lesson.objects.count() == 0 and len(queue.runs) == 0

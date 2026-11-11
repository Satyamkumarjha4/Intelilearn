"""Unit under test: `lessons.services.LessonService` and `QuizService`, the use cases behind the lessons API.

Why: these decide what may happen to a lesson. Starting one snapshots the model registry and settings, so an admin edit
never changes a lesson mid-flight; a quiz may be answered once, only when the lesson is waiting for it, and its answers
must be complete. Getting any of that wrong either corrupts a lesson's flow or lets a learner replay a diagnostic.

Use cases:
- creating a lesson snapshots the registry and the flow settings, queues a start run and enqueues it
- creating a lesson refuses when no model is bound for the first step, and leaves nothing behind
- creating a self-rated lesson stores the entry and the rating, covers the whole lesson in its one `lesson.create`,
  needs the planner (and, for a Beginner's stars, the prerequisite planner) bound, and queues the same start run
- creating a lesson stores its intent and its origin as the server verified them; a refused origin creates nothing and
  asks nothing
- a self-rated lesson that is stopped and retried carries on from where it stopped
- retrying a failed lesson queues a retry run; any other stage, or a run in progress, is refused
- stopping a run the worker never started remembers the stage the lesson waits in, and Retry puts it back there; a
  run the worker had started remembers no stage (the thread moves on while the Stop is being noticed, so the stage read
  at the click can already be one it has left), and the lesson stays failed until the node that runs moves it; either
  way Retry hands the retry run the answer the stopped run was about to give (for that kind of question only); a lesson
  that failed by itself, or whose stopped run was not the flow's, is retried as before
- deleting a lesson cancels its active runs and removes it with everything attached, including its checkpoints and
  model calls (erased first, so a failed erasure leaves the lesson there to be deleted again)
- an unreachable queue fails the run and the lesson, so Retry works once it is back
- the learner's quiz has no answers, explanations or concepts
- a quiz that does not exist yet is not found
- submitting grades the quiz, stores the attempt, queues a resume run and returns the score with the route
- submitting the prerequisite quiz returns a score without a route
- submitting is refused when the lesson is not waiting for that quiz, was already answered (even once the lesson has
  moved on), or a run is active
- incomplete or invalid answers are refused with the reason, and nothing is stored
- reviewing shows the learner's answers next to the correct ones, only after an attempt
- choosing a sheet resumes the flow, only while the lesson waits for the choice and with no run active
- creating a lesson that asks for sheets stores the intent, hands the run the sheets asked for, covers the quiz stage
  (or the whole lesson when self-rated) in its one `lesson.create` with the number of sheets and what they rest on,
  needs the sheet writer (and not the lesson planner) bound, plans no prerequisites for any stars, and refuses a body
  that asks for no sheets, an unknown sheet or sheets for a lesson
- sheets can be requested for any ready lesson (one with pages, a mastery lesson, a sheets-only one), as one kind
  or several at once, in the small graph; a request for a kind that exists names the kinds that exist and creates and
  asks nothing; a practice sheet cannot be requested; the lesson must be ready and have no run active
- a sheet is served with its practice solutions hidden until revealed (by id, several ids or all)
- a practice sheet is graded on submit: multiple choice and numerical are marked, the rest show their solution
- the kinds of sheet a lesson has are listed
- the document is served for a ready lesson only
- a crash report queues a runtime repair and counts against the cap; a stale version, the cap, a lesson that is not
  ready and a run in progress are refused, and nothing is queued
- a test submission marks the automatic answers at once and queues the open-ended ones for grading; with none to grade
  it is final at once; blank answers are never sent; unknown ids, odd values and long answers are refused; a lesson that
  is not ready (or is a mastery lesson) is refused; a submission can be read, only by its own lesson
- the test can be submitted once: a second go is refused with the first submission's id, whatever its status, and
  stores nothing, even when two submits slip past the first check together (the unique constraint says no, and the
  answer is the same 409 with the first one's id, never a 500)
- the learner's test has no answers, marking schemes or concepts, its total marks, and the one submission once made
- a failed grading is re-run on the stored answers (never new ones), only when it failed and no run is active
- the lesson's one submission can be read, and its absence is a 404
- a grading run that cannot be queued or is cancelled fails its submission
- an earlier version can be restored: the code being replaced is kept, the restored code gets a new code_version, and
  an unknown version, a lesson that is not ready or a run in progress are refused
"""

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from support.gates import CountingGate, RefusingGate
from support.lesson_data import make_final_test
from support.quiz_data import make_prerequisites, make_questions
from support.study_data import make_cheat_sheet, make_practice_sheet, make_revision_sheet

from lessons.attempts import AttemptService
from lessons.errors import (
    AlreadyAttempted,
    AlreadyExists,
    InvalidAnswers,
    LessonNotConfigured,
    MaterialNotFound,
    NotAttempted,
    NotFailed,
    QueueUnavailable,
    QuizNotFound,
    RepairLimitReached,
    RunInProgress,
    StaleCodeVersion,
    SubmissionNotFound,
    VersionNotFound,
    WrongStage,
)
from lessons.metering import ActionRefused
from lessons.models import (
    FlowSettings,
    GraphRun,
    Lesson,
    LessonVersion,
    Quiz,
    QuizAttempt,
    Stage,
    StudyMaterial,
    TestSubmission,
)
from lessons.services import (
    CodeService,
    LessonService,
    MaterialService,
    QuizService,
    RunDispatcher,
)
from lessons.stop_point import StopPoint

pytestmark = pytest.mark.django_db


class TestCreateLesson:
    def test_snapshots_the_registry_and_settings_and_enqueues_a_start_run(self, user, queue, bound_registry):
        lesson, run = LessonService(queue=queue).create(user, "  Binary search ", "for my exam")

        assert (lesson.owner, lesson.topic, lesson.user_context) == (user, "Binary search", "for my exam")
        assert lesson.stage == Stage.PREPARING_DIAGNOSTIC
        assert "diagnostic.generate" in lesson.config_snapshot["nodes"]
        assert lesson.config_snapshot["nodes"]["diagnostic.generate"]["chain"][0]["model_name"] == "fake-model"
        assert lesson.settings_snapshot == FlowSettings.load().snapshot()
        assert (run.lesson, run.graph, run.trigger, run.status) == (
            lesson, GraphRun.Graph.FLOW, GraphRun.Trigger.START, GraphRun.Status.QUEUED,
        )  # fmt: skip
        assert queue.runs == [run]

    def test_a_later_admin_edit_does_not_change_the_snapshot(self, user, queue, bound_registry):
        lesson, _ = LessonService(queue=queue).create(user, "Binary search")
        FlowSettings.objects.update_or_create(pk=1, defaults={"prereq_trigger_max_correct": 4})

        lesson.refresh_from_db()

        assert lesson.settings_snapshot["prereq_trigger_max_correct"] == 2

    def test_refuses_when_no_model_is_bound_for_the_first_step(self, user, queue, db):
        from llm_registry.node_configs import NodeConfigSync

        NodeConfigSync().ensure()

        with pytest.raises(LessonNotConfigured, match="diagnostic.generate"):
            LessonService(queue=queue).create(user, "Binary search")

        assert Lesson.objects.count() == 0 and queue.runs == []


class TestCreateSelfRated:
    def create(self, user, queue, halves=5, gate=None, **extra):
        return LessonService(queue=queue, gate=gate).create(
            user, "Binary search", entry="self_rating", self_rating_halves=halves, **extra
        )

    def test_stores_the_entry_and_the_rating_and_queues_the_start_run(self, user, queue, bound_registry):
        lesson, run = self.create(user, queue, halves=7)

        assert (lesson.entry, lesson.self_rating_halves, lesson.intent, lesson.origin) == (
            "self_rating", 7, "lesson", "direct",
        )  # fmt: skip
        assert (lesson.stage, lesson.level, lesson.level_source) == (Stage.PREPARING_DIAGNOSTIC, "", "")
        assert (run.graph, run.trigger) == (GraphRun.Graph.FLOW, GraphRun.Trigger.START) and queue.runs == [run]

    def test_a_quick_check_has_no_rating_even_if_one_is_passed(self, user, queue, bound_registry):
        lesson, _ = LessonService(queue=queue).create(user, "Binary search", self_rating_halves=7)

        assert (lesson.entry, lesson.self_rating_halves) == ("diagnostic", None)

    def test_asks_lesson_create_once_for_the_whole_lesson(self, user, queue, bound_registry):
        gate = CountingGate()

        lesson, run = self.create(user, queue, gate=gate)

        (asked,) = gate.authorized
        assert asked.size == {"entry": "self_rating", "intent": "lesson", "origin": "direct", "covers": "all"}
        assert asked.completes_at.to_payload() == {"kind": "stage", "stage": "ready"}
        assert run.payload["authorization"]["completes_at"] == {"kind": "stage", "stage": "ready"}

    def test_needs_a_rating(self, user, queue, bound_registry):
        with pytest.raises(ValueError, match="rating"):
            LessonService(queue=queue).create(user, "Binary search", entry="self_rating")

        assert Lesson.objects.count() == 0 and queue.runs == []

    def test_needs_the_lesson_planner_bound_but_not_the_quiz(self, user, queue, bound_registry):
        from llm_registry.models import NodeModelBinding

        NodeModelBinding.objects.filter(node__node_key="diagnostic.generate").delete()
        assert self.create(user, queue)[0].entry == "self_rating"
        NodeModelBinding.objects.filter(node__node_key="lesson.plan").delete()

        with pytest.raises(LessonNotConfigured, match="lesson.plan"):
            self.create(user, queue)

    @pytest.mark.parametrize(("halves", "needs_it"), [(2, True), (3, True), (4, False), (8, False), (10, False)])
    def test_only_a_beginners_stars_need_the_prerequisite_planner(self, user, queue, bound_registry, halves, needs_it):
        from llm_registry.models import NodeModelBinding

        NodeModelBinding.objects.filter(node__node_key="prerequisites.plan").delete()

        if needs_it:
            with pytest.raises(LessonNotConfigured, match="prerequisites.plan"):
                self.create(user, queue, halves=halves)
            assert Lesson.objects.count() == 0
        else:
            assert self.create(user, queue, halves=halves)[0].self_rating_halves == halves

    def test_a_refused_ask_creates_nothing(self, user, queue, bound_registry):
        with pytest.raises(ActionRefused):
            self.create(user, queue, gate=RefusingGate())

        assert Lesson.objects.count() == 0 and queue.runs == []

    def test_a_stopped_self_rated_lesson_is_retried_from_where_it_stopped(self, user, queue, bound_registry):
        class Silent:
            def publish(self, run_id, event):
                pass

        service = LessonService(queue=queue, events=Silent())
        lesson, run = self.create(user, queue)
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING, started_at=timezone.now())

        service.cancel(GraphRun.objects.get(pk=run.pk))
        lesson.refresh_from_db()
        assert lesson.stage == Stage.FAILED

        retry = service.retry(lesson)
        lesson.refresh_from_db()

        assert (retry.trigger, lesson.stage) == (GraphRun.Trigger.RETRY, Stage.FAILED)  # its node moves it on


class TestCreateSheets:
    def create(self, user, queue, sheets=("cheat_sheet", "revision_sheet"), gate=None, **extra):
        return LessonService(queue=queue, gate=gate).create(
            user, "Binary search", intent="sheets", sheets=list(sheets), **extra
        )

    def test_stores_the_intent_and_hands_the_run_the_sheets_asked_for(self, user, queue, bound_registry):
        lesson, run = self.create(user, queue, sheets=("revision_sheet",))

        assert (lesson.intent, lesson.entry, lesson.stage, lesson.route) == (
            "sheets", "diagnostic", Stage.PREPARING_DIAGNOSTIC, "",
        )  # fmt: skip
        assert run.payload["input"] == {"sheet_kinds": ["revision_sheet"]} and queue.runs == [run]

    def test_a_quick_check_asks_for_the_quiz_stage_with_the_sheets_resting_on_the_quiz(
        self, user, queue, bound_registry
    ):
        gate = CountingGate()

        _, run = self.create(user, queue, gate=gate)

        (asked,) = gate.authorized
        assert asked.size == {
            "entry": "diagnostic", "intent": "sheets", "origin": "direct", "covers": "diagnostic", "sheets": 2,
            "grounding": "quiz",
        }  # fmt: skip
        assert asked.completes_at.to_payload() == {"kind": "stage", "stage": "awaiting_diagnostic"}

    def test_a_self_rated_lesson_covers_everything_with_the_sheets_resting_on_the_level_alone(
        self, user, queue, bound_registry
    ):
        gate = CountingGate()

        lesson, _ = self.create(
            user, queue, sheets=("cheat_sheet",), gate=gate, entry="self_rating", self_rating_halves=2
        )

        (asked,) = gate.authorized
        assert asked.size == {
            "entry": "self_rating", "intent": "sheets", "origin": "direct", "covers": "all", "sheets": 1,
            "grounding": "none",
        }  # fmt: skip
        assert asked.completes_at.to_payload() == {"kind": "stage", "stage": "ready"}
        assert (lesson.entry, lesson.self_rating_halves) == ("self_rating", 2)

    def test_it_needs_the_sheet_writer_bound_and_not_the_lesson_planner(self, user, queue, bound_registry):
        from llm_registry.models import NodeModelBinding

        NodeModelBinding.objects.filter(node__node_key__in=["lesson.plan", "prerequisites.plan"]).delete()
        assert self.create(user, queue, entry="self_rating", self_rating_halves=2)[0].intent == "sheets"
        NodeModelBinding.objects.filter(node__node_key="study.generate").delete()

        with pytest.raises(LessonNotConfigured, match="study.generate"):
            self.create(user, queue, entry="self_rating", self_rating_halves=2)
        with pytest.raises(LessonNotConfigured, match="study.generate"):
            self.create(user, queue)

    def test_a_quick_check_for_sheets_needs_the_quiz_writer_too(self, user, queue, bound_registry):
        from llm_registry.models import NodeModelBinding

        NodeModelBinding.objects.filter(node__node_key="diagnostic.generate").delete()

        with pytest.raises(LessonNotConfigured, match="diagnostic.generate"):
            self.create(user, queue)

    @pytest.mark.parametrize("sheets", [(), ("practice_sheet",), ("poster",)])
    def test_the_sheets_asked_for_must_be_one_or_both_of_the_two_offered(self, user, queue, bound_registry, sheets):
        with pytest.raises(ValueError, match="sheet"):
            self.create(user, queue, sheets=sheets)

        assert Lesson.objects.count() == 0 and queue.runs == []

    def test_a_kind_asked_for_twice_is_written_once_and_in_the_order_they_are_written(
        self, user, queue, bound_registry
    ):
        lesson, run = self.create(user, queue, sheets=("revision_sheet", "cheat_sheet", "revision_sheet"))

        assert run.payload["input"] == {"sheet_kinds": ["cheat_sheet", "revision_sheet"]}

    def test_a_lesson_that_is_not_sheets_takes_no_sheets(self, user, queue, bound_registry):
        with pytest.raises(ValueError, match="sheet"):
            LessonService(queue=queue).create(user, "Binary search", sheets=["cheat_sheet"])

        assert Lesson.objects.count() == 0


class TestCreateOrigin:
    def test_a_direct_lesson_stores_its_origin(self, user, queue, bound_registry):
        lesson, _ = LessonService(queue=queue).create(user, "Binary search")

        assert (lesson.origin, lesson.recommended_from, lesson.intent) == ("direct", None, "lesson")

    def test_a_verified_recommendation_is_stored_and_sent_to_the_gate(self, user, queue, bound_registry, lesson):
        attempt = TestSubmission.objects.create(
            lesson=lesson, status="graded", result={"topics_to_revisit": ["Off by one"], "score": {}}
        )
        gate = CountingGate()

        made, _ = LessonService(queue=queue, gate=gate).create(
            user,
            "Off by one",
            origin="recommendation",
            recommended_from={"attempt_id": attempt.pk, "topic": "off by one"},
        )

        assert made.origin == "recommendation"
        assert made.recommended_from == {"attempt_id": str(attempt.pk), "topic": "Off by one"}
        assert gate.authorized[0].size["origin"] == "recommendation"

    @pytest.mark.parametrize("origin", ["followup", "quiz_result"])
    def test_an_origin_the_server_alone_can_set_is_refused_before_anything_is_asked_or_created(
        self, user, queue, bound_registry, origin
    ):
        gate = CountingGate()

        with pytest.raises(ValidationError):
            LessonService(queue=queue, gate=gate).create(user, "Binary search", origin=origin)

        assert gate.authorized == [] and queue.runs == []
        assert not Lesson.objects.filter(topic="Binary search").exists()


class TestStopPointSettle:
    """The worker noticed the Stop and knows where the thread is."""

    @pytest.fixture
    def stopped(self, make_lesson):
        lesson = make_lesson(stage=Stage.AWAITING_DIAGNOSTIC)
        run = GraphRun.objects.create(
            lesson=lesson, trigger=GraphRun.Trigger.RESUME_DIAGNOSTIC, status=GraphRun.Status.CANCELLED,
            started_at=timezone.now(), payload={"resume": "a", "stopped_in": ""},
        )  # fmt: skip
        return lesson, run

    @pytest.mark.parametrize(("kind", "stage"), [
        ("diagnostic", "awaiting_diagnostic"), ("prerequisite", "awaiting_prerequisite"),
        ("mastery_choice", "awaiting_choice"), ("retry", ""), (None, ""),
    ])  # fmt: skip
    def test_a_thread_at_a_question_is_in_that_questions_stage_and_a_moving_one_in_none(self, stopped, kind, stage):
        _, run = stopped

        StopPoint().settle(run, kind)

        run.refresh_from_db()
        assert run.payload["stopped_in"] == stage and run.payload["resume"] == "a"

    def test_a_stop_of_something_other_than_the_flow_is_left_alone(self, make_lesson):
        run = GraphRun.objects.create(
            lesson=make_lesson(), graph=GraphRun.Graph.GRADE_TEST, trigger=GraphRun.Trigger.GRADE,
            status=GraphRun.Status.CANCELLED,
        )  # fmt: skip

        StopPoint().settle(run, "diagnostic")

        run.refresh_from_db()
        assert "stopped_in" not in run.payload


class TestRetry:
    def test_a_failed_lesson_gets_a_retry_run(self, make_lesson, queue):
        lesson = make_lesson(stage=Stage.FAILED, error="boom")

        run = LessonService(queue=queue).retry(lesson)

        assert (run.trigger, run.status, run.graph) == (
            GraphRun.Trigger.RETRY, GraphRun.Status.QUEUED, GraphRun.Graph.FLOW,
        )  # fmt: skip
        assert queue.runs == [run]

    @pytest.fixture
    def service(self, queue):
        class Silent:
            def publish(self, run_id, event):
                pass

        return LessonService(queue=queue, events=Silent())

    @pytest.mark.parametrize(
        ("trigger", "stage", "kind"),
        [
            (GraphRun.Trigger.RESUME_DIAGNOSTIC, Stage.AWAITING_DIAGNOSTIC, "diagnostic"),
            (GraphRun.Trigger.RESUME_PREREQUISITE, Stage.AWAITING_PREREQUISITE, "prerequisite"),
            (GraphRun.Trigger.RESUME_CHOICE, Stage.AWAITING_CHOICE, "mastery_choice"),
        ],
    )
    def test_a_run_nobody_started_goes_back_to_the_stage_it_waited_in_and_the_retry_carries_the_answer(
        self, service, make_lesson, queue, trigger, stage, kind
    ):
        lesson = make_lesson(stage=stage)
        run = GraphRun.objects.create(
            lesson=lesson, trigger=trigger, status=GraphRun.Status.QUEUED, payload={"resume": "the-answer"}
        )  # the thread still waits at the question, so the stage is still true

        service.cancel(run)
        lesson.refresh_from_db()
        assert lesson.stage == Stage.FAILED

        retry = service.retry(lesson)

        lesson.refresh_from_db()
        assert (lesson.stage, lesson.error) == (stage, "")
        assert retry.payload == {"resume": "the-answer", "resume_for": kind}
        assert queue.runs == [retry]

    @pytest.mark.parametrize(
        ("trigger", "stage", "kind"),
        [
            (GraphRun.Trigger.RESUME_DIAGNOSTIC, Stage.AWAITING_DIAGNOSTIC, "diagnostic"),
            (GraphRun.Trigger.RESUME_PREREQUISITE, Stage.AWAITING_PREREQUISITE, "prerequisite"),
            (GraphRun.Trigger.RESUME_CHOICE, Stage.AWAITING_CHOICE, "mastery_choice"),
        ],
    )
    def test_a_run_the_worker_had_started_remembers_no_stage_but_still_carries_the_answer(
        self, service, make_lesson, queue, trigger, stage, kind
    ):
        lesson = make_lesson(stage=stage)  # the stage at the click: the thread is already grading the answer
        run = GraphRun.objects.create(
            lesson=lesson, trigger=trigger, status=GraphRun.Status.RUNNING, started_at=timezone.now(),
            payload={"resume": "the-answer"},
        )  # fmt: skip

        service.cancel(run)
        retry = service.retry(Lesson.objects.get(pk=lesson.pk))

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.FAILED  # the node that runs moves it, as for any retry
        assert retry.payload == {"resume": "the-answer", "resume_for": kind}

    def test_a_stopped_build_stays_failed_until_its_node_runs_with_nothing_to_carry(self, service, make_lesson):
        lesson = make_lesson(stage=Stage.GENERATING_LESSON)
        run = GraphRun.objects.create(
            lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.RUNNING, started_at=timezone.now()
        )

        service.cancel(run)
        retry = service.retry(Lesson.objects.get(pk=lesson.pk))

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.FAILED
        assert retry.payload == {}

    def test_a_run_nobody_started_that_was_a_first_start_goes_back_to_its_first_stage(self, service, make_lesson):
        lesson = make_lesson(stage=Stage.PREPARING_DIAGNOSTIC)
        run = GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.QUEUED)

        service.cancel(run)
        service.retry(Lesson.objects.get(pk=lesson.pk))

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.PREPARING_DIAGNOSTIC

    def test_a_lesson_that_failed_by_itself_stays_failed_until_its_node_runs_again(self, service, make_lesson):
        lesson = make_lesson(stage=Stage.FAILED, error="boom")
        GraphRun.objects.create(
            lesson=lesson, trigger=GraphRun.Trigger.RESUME_DIAGNOSTIC, status=GraphRun.Status.FAILED,
            payload={"resume": "old"},
        )  # fmt: skip

        retry = service.retry(lesson)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.FAILED and retry.payload == {}

    def test_a_stop_that_came_after_the_lesson_failed_or_finished_remembers_nothing(self, service, make_lesson):
        ready = make_lesson(stage=Stage.READY)
        grading = GraphRun.objects.create(
            lesson=ready,
            graph=GraphRun.Graph.GRADE_TEST,
            trigger=GraphRun.Trigger.GRADE,
            status=GraphRun.Status.RUNNING,
        )
        failed = make_lesson(stage=Stage.FAILED)
        flow = GraphRun.objects.create(lesson=failed, trigger=GraphRun.Trigger.RETRY, status=GraphRun.Status.RUNNING)

        service.cancel(grading)
        service.cancel(flow)

        grading.refresh_from_db()
        flow.refresh_from_db()
        assert "stopped_in" not in grading.payload and "stopped_in" not in flow.payload
        assert Lesson.objects.get(pk=ready.pk).stage == Stage.READY

    @pytest.mark.parametrize("stage", [Stage.AWAITING_DIAGNOSTIC, Stage.GENERATING_LESSON, Stage.READY])
    def test_other_stages_cannot_be_retried(self, make_lesson, queue, stage):
        with pytest.raises(WrongStage):
            LessonService(queue=queue).retry(make_lesson(stage=stage))

        assert queue.runs == []

    def test_a_retry_already_running_is_refused(self, make_lesson, queue):
        lesson = make_lesson(stage=Stage.FAILED)
        GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.RETRY, status=GraphRun.Status.RUNNING)

        with pytest.raises(RunInProgress):
            LessonService(queue=queue).retry(lesson)


class TestDelete:
    def test_cancels_active_runs_and_removes_the_lesson_with_its_rows(self, lesson, queue):
        Quiz.objects.create(lesson=lesson, kind="diagnostic", questions=[])
        run = GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.RUNNING)

        cancelled = LessonService(queue=queue).delete(lesson)

        assert cancelled == [run.pk]
        assert not Lesson.objects.filter(pk=lesson.pk).exists()
        assert Quiz.objects.count() == 0 and GraphRun.objects.count() == 0

    def test_erases_the_checkpoints_and_model_calls_before_the_lesson_row_goes(self, lesson, queue):
        seen, lesson_id = [], lesson.pk

        class Erasure:
            def erase(self, doomed):
                seen.append((doomed.pk, Lesson.objects.filter(pk=doomed.pk).exists()))

        LessonService(queue=queue, erasure=Erasure()).delete(lesson)

        assert seen == [(lesson_id, True)]
        assert not Lesson.objects.filter(pk=lesson_id).exists()

    def test_a_failed_erasure_leaves_the_lesson_to_be_deleted_again(self, lesson, queue):
        class Erasure:
            def erase(self, doomed):
                raise RuntimeError("database down")

        with pytest.raises(RuntimeError):
            LessonService(queue=queue, erasure=Erasure()).delete(lesson)

        assert Lesson.objects.filter(pk=lesson.pk).exists()


def make_quiz(lesson, kind="diagnostic", stage=None):
    questions = make_questions() if kind == "diagnostic" else make_prerequisites()[1]
    quiz = Quiz.objects.create(lesson=lesson, kind=kind, questions=questions)
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=stage or Stage(f"awaiting_{kind}"), settings_snapshot={"prereq_trigger_max_correct": 2}
    )
    lesson.refresh_from_db()
    return quiz


def answers_for(quiz, right):
    return {q["id"]: q["correct_index"] if n < right else (q["correct_index"] + 1) % 4
            for n, q in enumerate(quiz.questions)}  # fmt: skip


class TestQuizForLearner:
    def test_has_no_answers_explanations_or_concepts(self, lesson):
        quiz = make_quiz(lesson)

        body = QuizService().for_learner(lesson, "diagnostic")

        assert body["quiz_id"] == str(quiz.id) and body["kind"] == "diagnostic" and body["allow_dont_know"] is True
        assert set(body["questions"][0]) == {"id", "band", "question", "options"}
        assert "correct_index" not in str(body) and "explanation" not in str(body)

    def test_a_quiz_that_was_not_published_is_not_found(self, lesson):
        with pytest.raises(QuizNotFound):
            QuizService().for_learner(lesson, "diagnostic")

    def test_an_unknown_kind_is_not_found(self, lesson):
        with pytest.raises(QuizNotFound):
            QuizService().for_learner(lesson, "final")


class TestSubmit:
    def test_grades_stores_the_attempt_and_queues_a_resume_run(self, lesson, queue):
        quiz = make_quiz(lesson)

        summary, run = QuizService(queue=queue).submit(lesson, "diagnostic", answers_for(quiz, 6))

        attempt = QuizAttempt.objects.get(quiz=quiz)
        assert summary["correct"] == 6 and summary["total"] == 10 and summary["route"] == "lesson"
        assert attempt.result["correct"] == 6 and attempt.answers["q1"] == 0
        assert (run.trigger, run.status, run.payload) == (
            GraphRun.Trigger.RESUME_DIAGNOSTIC, GraphRun.Status.QUEUED, {"resume": str(attempt.id)},
        )  # fmt: skip
        assert queue.runs == [run]

    @pytest.mark.parametrize(
        ("right", "route"), [(0, "prerequisite"), (2, "prerequisite"), (3, "lesson"), (10, "mastery")]
    )
    def test_the_route_follows_the_lessons_settings(self, lesson, queue, right, route):
        quiz = make_quiz(lesson)

        summary, _ = QuizService(queue=queue).submit(lesson, "diagnostic", answers_for(quiz, right))

        assert summary["route"] == route

    def test_the_prerequisite_quiz_returns_a_score_without_a_route(self, lesson, queue):
        quiz = make_quiz(lesson, "prerequisite")

        summary, run = QuizService(queue=queue).submit(lesson, "prerequisite", answers_for(quiz, 3))

        assert summary["correct"] == 3 and "route" not in summary
        assert run.trigger == GraphRun.Trigger.RESUME_PREREQUISITE

    def test_i_dont_know_scores_as_wrong(self, lesson, queue):
        quiz = make_quiz(lesson)
        answers = answers_for(quiz, 10) | {"q1": "dont_know"}

        summary, _ = QuizService(queue=queue).submit(lesson, "diagnostic", answers)

        assert (summary["correct"], summary["dont_know"]) == (9, 1)

    def test_refuses_when_the_lesson_is_not_waiting_for_this_quiz(self, lesson, queue):
        quiz = make_quiz(lesson, stage=Stage.GENERATING_LESSON)

        with pytest.raises(WrongStage):
            QuizService(queue=queue).submit(lesson, "diagnostic", answers_for(quiz, 5))

        assert QuizAttempt.objects.count() == 0 and queue.runs == []

    def test_refuses_a_second_attempt(self, lesson, queue):
        quiz = make_quiz(lesson)
        QuizAttempt.objects.create(quiz=quiz, answers={}, result={})

        with pytest.raises(AlreadyAttempted):
            QuizService(queue=queue).submit(lesson, "diagnostic", answers_for(quiz, 5))

    def test_a_second_attempt_is_still_already_attempted_once_the_lesson_has_moved_on(self, lesson, queue):
        quiz = make_quiz(lesson)
        QuizAttempt.objects.create(quiz=quiz, answers={}, result={})
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)

        with pytest.raises(AlreadyAttempted):
            QuizService(queue=queue).submit(lesson, "diagnostic", answers_for(quiz, 5))

        assert QuizAttempt.objects.count() == 1 and queue.runs == []

    def test_refuses_while_a_run_is_still_active(self, lesson, queue):
        quiz = make_quiz(lesson)
        GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.RUNNING)

        with pytest.raises(RunInProgress):
            QuizService(queue=queue).submit(lesson, "diagnostic", answers_for(quiz, 5))

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            (lambda a: a.pop("q10"), "missing: q10"),
            (lambda a: a.update(zzz=1), "zzz"),
            (lambda a: a.update(q3=7), "q3"),
            (lambda a: a.update(q3="maybe"), "q3"),
        ],
        ids=["missing", "unknown-id", "out-of-range", "not-an-answer"],
    )
    def test_refuses_incomplete_or_invalid_answers_and_stores_nothing(self, lesson, queue, change, message):
        quiz = make_quiz(lesson)
        answers = answers_for(quiz, 5)
        change(answers)

        with pytest.raises(InvalidAnswers, match=message):
            QuizService(queue=queue).submit(lesson, "diagnostic", answers)

        assert QuizAttempt.objects.count() == 0 and queue.runs == []

    def test_answers_must_be_an_object(self, lesson, queue):
        make_quiz(lesson)

        with pytest.raises(InvalidAnswers):
            QuizService(queue=queue).submit(lesson, "diagnostic", ["q1"])

    def test_a_quiz_that_does_not_exist_is_not_found(self, lesson, queue):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC)
        lesson.refresh_from_db()

        with pytest.raises(QuizNotFound):
            QuizService(queue=queue).submit(lesson, "diagnostic", {})


class TestReview:
    def test_shows_the_learners_answers_beside_the_correct_ones_and_the_explanations(self, lesson, queue):
        quiz = make_quiz(lesson)
        service = QuizService(queue=queue)
        service.submit(lesson, "diagnostic", answers_for(quiz, 6) | {"q10": "dont_know"})

        body = service.review(lesson, "diagnostic")

        first, last = body["questions"][0], body["questions"][-1]
        assert first["answer"] == 0 and first["correct_index"] == 0 and first["correct"] is True
        assert first["explanation"] == "Because of concept basic 0."
        assert last["answer"] == "dont_know" and last["correct"] is False
        assert body["result"]["correct"] == 6
        assert body["submitted_at"] == QuizAttempt.objects.get(quiz=quiz).submitted_at

    def test_is_refused_before_the_attempt(self, lesson):
        make_quiz(lesson)

        with pytest.raises(NotAttempted):
            QuizService().review(lesson, "diagnostic")

    def test_a_missing_quiz_is_not_found(self, lesson):
        with pytest.raises(QuizNotFound):
            QuizService().review(lesson, "prerequisite")


class TestDispatcher:
    class BrokenQueue:
        def enqueue(self, run):
            raise QueueUnavailable()

    def test_an_unreachable_queue_fails_the_run_and_the_lesson_so_retry_works_later(self, lesson):
        run = GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START)

        with pytest.raises(QueueUnavailable):
            RunDispatcher(self.BrokenQueue()).dispatch(run)

        run.refresh_from_db()
        lesson.refresh_from_db()
        assert run.status == GraphRun.Status.FAILED and "queue" in run.error
        assert lesson.stage == Stage.FAILED and lesson.error == run.error


def mastery_lesson(make_lesson, stage=Stage.AWAITING_CHOICE):
    return make_lesson(stage=stage, route="mastery")


class TestChoose:
    @pytest.mark.parametrize("choice", ["lesson", "sheets"])
    def test_resumes_the_flow_with_the_choice(self, make_lesson, queue, choice):
        lesson = mastery_lesson(make_lesson)

        run = MaterialService(queue=queue).choose(lesson, choice)

        assert (run.graph, run.trigger, run.payload) == (
            GraphRun.Graph.FLOW, GraphRun.Trigger.RESUME_CHOICE, {"resume": {"choice": choice}},
        )  # fmt: skip
        assert queue.runs == [run]

    @pytest.mark.parametrize("choice", ["poster", "", "practice", "cheat_sheet", "revision_sheet", "practice_sheet"])
    def test_a_choice_that_is_not_offered_is_refused_and_nothing_is_queued(self, make_lesson, queue, choice):
        with pytest.raises(InvalidAnswers):
            MaterialService(queue=queue).choose(mastery_lesson(make_lesson), choice)

        assert queue.runs == [] and GraphRun.objects.count() == 0

    @pytest.mark.parametrize("stage", [Stage.AWAITING_DIAGNOSTIC, Stage.GENERATING_MATERIAL, Stage.READY])
    def test_is_refused_unless_the_lesson_waits_for_the_choice(self, make_lesson, queue, stage):
        with pytest.raises(WrongStage):
            MaterialService(queue=queue).choose(mastery_lesson(make_lesson, stage), "sheets")

        assert queue.runs == []

    def test_is_refused_while_a_run_is_active(self, make_lesson, queue):
        lesson = mastery_lesson(make_lesson)
        GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.RUNNING)

        with pytest.raises(RunInProgress):
            MaterialService(queue=queue).choose(lesson, "sheets")


class TestRequestExtra:
    def ready(self, make_lesson, **fields):
        return make_lesson(stage=Stage.READY, **{"route": "lesson", **fields})

    def test_queues_the_study_material_graph_with_the_sheets_asked_for(self, make_lesson, queue):
        lesson = mastery_lesson(make_lesson, Stage.READY)

        run = MaterialService(queue=queue).request_extra(lesson, "revision_sheet")

        assert (run.graph, run.trigger) == (GraphRun.Graph.STUDY_MATERIAL, GraphRun.Trigger.EXTRA_MATERIAL)
        assert run.payload == {"input": {"sheet_kinds": ["revision_sheet"], "extra_material": True}}
        assert queue.runs == [run]

    @pytest.mark.parametrize("fields", [{"route": "lesson"}, {"route": "mastery"}, {"intent": "sheets", "route": ""}])
    def test_any_ready_lesson_can_get_sheets(self, make_lesson, queue, fields):
        lesson = make_lesson(stage=Stage.READY, **fields)

        run = MaterialService(queue=queue).request_extra(lesson, "cheat_sheet")

        assert run.graph == GraphRun.Graph.STUDY_MATERIAL and queue.runs == [run]

    @pytest.mark.parametrize("kinds", [["cheat_sheet", "revision_sheet"], ("revision_sheet", "cheat_sheet")])
    def test_both_can_be_asked_for_in_one_request_in_the_order_they_are_written(self, make_lesson, queue, kinds):
        lesson = self.ready(make_lesson)

        run = MaterialService(queue=queue).request_extra(lesson, kinds)

        assert run.payload["input"]["sheet_kinds"] == ["cheat_sheet", "revision_sheet"]
        assert len(queue.runs) == 1  # one request, one run

    def test_a_kind_the_lesson_already_has_is_refused_naming_it(self, make_lesson, queue):
        lesson = mastery_lesson(make_lesson, Stage.READY)
        StudyMaterial.objects.create(lesson=lesson, kind="cheat_sheet", content=make_cheat_sheet())

        with pytest.raises(AlreadyExists) as caught:
            MaterialService(queue=queue).request_extra(lesson, "cheat_sheet")

        assert caught.value.extra == {"kinds": ["cheat_sheet"]} and queue.runs == []

    def test_asking_for_both_while_one_exists_names_the_one_that_exists_and_creates_nothing(self, make_lesson, queue):
        from support.gates import CountingGate

        lesson = self.ready(make_lesson)
        StudyMaterial.objects.create(lesson=lesson, kind="revision_sheet", content=make_revision_sheet())
        gate = CountingGate()

        with pytest.raises(AlreadyExists) as caught:
            MaterialService(queue=queue, gate=gate).request_extra(lesson, ["cheat_sheet", "revision_sheet"])

        assert caught.value.extra == {"kinds": ["revision_sheet"]}
        assert GraphRun.objects.count() == 0 and gate.authorized == [] and queue.runs == []

    def test_the_missing_one_can_be_asked_for_alone_afterwards(self, make_lesson, queue):
        lesson = self.ready(make_lesson)
        StudyMaterial.objects.create(lesson=lesson, kind="revision_sheet", content=make_revision_sheet())

        run = MaterialService(queue=queue).request_extra(lesson, ["cheat_sheet"])

        assert run.payload["input"]["sheet_kinds"] == ["cheat_sheet"]

    @pytest.mark.parametrize("kinds", ["practice_sheet", ["cheat_sheet", "practice_sheet"], "poster", [], ()])
    def test_only_a_cheat_sheet_and_a_revision_sheet_can_be_asked_for(self, make_lesson, queue, kinds):
        with pytest.raises(ValueError, match="sheet"):
            MaterialService(queue=queue).request_extra(self.ready(make_lesson), kinds)

        assert GraphRun.objects.count() == 0

    @pytest.mark.parametrize("stage", [Stage.AWAITING_CHOICE, Stage.GENERATING_LESSON, Stage.FAILED])
    def test_a_lesson_that_is_not_ready_cannot_get_sheets(self, make_lesson, queue, stage):
        with pytest.raises(WrongStage):
            MaterialService(queue=queue).request_extra(make_lesson(stage=stage, route="lesson"), "cheat_sheet")

    def test_one_run_at_a_time(self, make_lesson, queue):
        lesson = mastery_lesson(make_lesson, Stage.READY)
        MaterialService(queue=queue).request_extra(lesson, "cheat_sheet")

        with pytest.raises(RunInProgress):
            MaterialService(queue=queue).request_extra(lesson, "revision_sheet")


class TestGetMaterial:
    def stored(self, lesson, kind="practice_sheet", make=make_practice_sheet):
        return StudyMaterial.objects.create(lesson=lesson, kind=kind, content=make())

    def test_serves_a_sheet_that_has_no_solutions_to_hide_as_is(self, lesson):
        self.stored(lesson, "cheat_sheet", make_cheat_sheet)

        body = MaterialService().get(lesson, "cheat_sheet")

        assert body == {"kind": "cheat_sheet", "content": make_cheat_sheet(), "solutions": {}}

    def test_a_practice_sheet_has_no_solutions_until_revealed(self, lesson):
        self.stored(lesson)

        body = MaterialService().get(lesson, "practice_sheet")

        text = str(body)
        assert body["solutions"] == {} and "correct_index" not in text and "model_answer" not in text
        assert len(body["content"]["questions"]) == 15

    def test_reveals_the_solutions_of_the_questions_asked_for(self, lesson):
        self.stored(lesson)

        body = MaterialService().get(lesson, "practice_sheet", reveal=["t1", "t2", "zzz"])

        assert set(body["solutions"]) == {"t1", "t2"}
        assert body["solutions"]["t1"]["correct_index"] == 1  # t1 is the first multiple-choice question
        assert body["solutions"]["t2"]["answer"] == 4.0  # t2 is numerical
        assert "question" not in body["solutions"]["t1"] and "options" not in body["solutions"]["t1"]

    def test_reveals_everything_for_all(self, lesson):
        self.stored(lesson)

        body = MaterialService().get(lesson, "practice_sheet", reveal=["all"])

        assert len(body["solutions"]) == 15

    def test_a_sheet_that_does_not_exist_is_not_found(self, lesson):
        with pytest.raises(MaterialNotFound):
            MaterialService().get(lesson, "cheat_sheet")

    def test_an_unknown_kind_is_not_found(self, lesson):
        with pytest.raises(MaterialNotFound):
            MaterialService().get(lesson, "poster")

    def test_lists_the_kinds_a_lesson_has(self, lesson):
        self.stored(lesson, "revision_sheet", make_revision_sheet)
        self.stored(lesson, "cheat_sheet", make_cheat_sheet)

        assert MaterialService().kinds(lesson) == ["cheat_sheet", "revision_sheet"]


class TestGradePractice:
    def test_marks_what_can_be_marked_and_shows_every_solution(self, lesson):
        StudyMaterial.objects.create(lesson=lesson, kind="practice_sheet", content=make_practice_sheet())
        answers = {"t1": 1, "t2": "4.0", "t3": "my words", "t4": 2}

        result = MaterialService().grade_practice(lesson, answers)

        by_id = {r["id"]: r for r in result["results"]}
        sheet = {q["id"]: q for q in make_practice_sheet()["questions"]}
        assert by_id["t1"]["correct"] is True and by_id["t1"]["awarded"] == sheet["t1"]["marks"]
        assert by_id["t2"]["correct"] is True
        assert by_id["t3"]["correct"] is None and by_id["t3"]["solution"]["model_answer"] == "Halve the range."
        assert [c["marks"] for c in by_id["t3"]["solution"]["criteria"]] == [1, sheet["t3"]["marks"] - 1]
        assert by_id["t4"]["correct"] is False and by_id["t4"]["solution"]["correct_index"] == 1
        assert result["score"]["awarded"] == sheet["t1"]["marks"] + sheet["t2"]["marks"]
        assert result["score"]["open_marks"] == sum(q["marks"] for q in sheet.values() if q["type"] == "short_answer")

    def test_unanswered_questions_are_wrong_for_the_kinds_that_can_be_marked(self, lesson):
        StudyMaterial.objects.create(lesson=lesson, kind="practice_sheet", content=make_practice_sheet())

        result = MaterialService().grade_practice(lesson, {})

        assert result["score"]["awarded"] == 0 and result["score"]["marked"] == 10

    def test_needs_a_practice_sheet(self, lesson):
        with pytest.raises(MaterialNotFound):
            MaterialService().grade_practice(lesson, {})

    def test_answers_must_be_an_object(self, lesson):
        StudyMaterial.objects.create(lesson=lesson, kind="practice_sheet", content=make_practice_sheet())

        with pytest.raises(InvalidAnswers):
            MaterialService().grade_practice(lesson, ["t1"])


def ready_lesson(make_lesson, **fields):
    defaults = {"stage": Stage.READY, "code": "CODE v1", "code_parts": {"pages": {}}, "code_version": 1,
                "settings_snapshot": {"max_auto_runtime_repairs": 2}}  # fmt: skip
    return make_lesson(**defaults | fields)


ERROR = {"message": "Interactive_x crashed", "page": "core"}


class TestDocument:
    def test_a_ready_lesson_is_served_with_its_code_version(self, make_lesson):
        lesson = ready_lesson(make_lesson)

        body = CodeService().document(lesson)

        assert (body["code"], body["code_version"]) == ("CODE v1", 1) and "pages" in body["data"]

    @pytest.mark.parametrize("fields", [{"stage": Stage.GENERATING_LESSON}, {"code": ""}])
    def test_a_lesson_that_is_not_ready_has_no_document(self, make_lesson, fields):
        with pytest.raises(WrongStage):
            CodeService().document(ready_lesson(make_lesson, **fields))


class TestRequestRepair:
    def test_queues_a_runtime_repair_with_the_error_and_the_version(self, make_lesson, queue):
        lesson = ready_lesson(make_lesson)

        run = CodeService(queue=queue).request_repair(lesson, ERROR, 1)

        assert (run.graph, run.trigger) == (GraphRun.Graph.RUNTIME_REPAIR, GraphRun.Trigger.REPAIR)
        assert run.payload == {"input": {"repair_error": ERROR, "expected_code_version": 1}}
        assert queue.runs == [run]

    def test_each_request_counts_against_the_cap_until_it_is_reached(self, make_lesson, queue):
        lesson = ready_lesson(make_lesson)
        service = CodeService(queue=queue)

        for _ in range(2):
            run = service.request_repair(lesson, ERROR, 1)
            GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.FAILED)

        with pytest.raises(RepairLimitReached):
            service.request_repair(lesson, ERROR, 1)
        assert Lesson.objects.get(pk=lesson.pk).runtime_repairs == 2 and len(queue.runs) == 2

    def test_a_snapshot_without_the_setting_uses_the_default_cap(self, make_lesson, queue):
        lesson = ready_lesson(make_lesson, settings_snapshot={}, runtime_repairs=CodeService.DEFAULT_REPAIR_LIMIT)

        with pytest.raises(RepairLimitReached):
            CodeService(queue=queue).request_repair(lesson, ERROR, 1)

    def test_a_stale_code_version_is_refused(self, make_lesson, queue):
        lesson = ready_lesson(make_lesson, code_version=3)

        with pytest.raises(StaleCodeVersion):
            CodeService(queue=queue).request_repair(lesson, ERROR, 2)
        assert queue.runs == [] and Lesson.objects.get(pk=lesson.pk).runtime_repairs == 0

    def test_a_lesson_that_is_not_ready_is_refused(self, make_lesson, queue):
        with pytest.raises(WrongStage):
            CodeService(queue=queue).request_repair(ready_lesson(make_lesson, stage=Stage.FAILED), ERROR, 1)

    def test_one_run_at_a_time(self, make_lesson, queue):
        lesson = ready_lesson(make_lesson)
        CodeService(queue=queue).request_repair(lesson, ERROR, 1)

        with pytest.raises(RunInProgress):
            CodeService(queue=queue).request_repair(lesson, ERROR, 1)


class TestRestore:
    def versioned(self, make_lesson):
        lesson = ready_lesson(make_lesson, code="CODE v2", code_parts={"v": 2}, code_version=2)
        LessonVersion.objects.create(lesson=lesson, code_version=1, code="CODE v1", code_parts={"v": 1}, reason="r")
        return lesson

    def test_the_old_code_comes_back_under_a_new_version_and_the_replaced_code_is_kept(self, make_lesson):
        lesson = self.versioned(make_lesson)

        restored = CodeService().restore(lesson, 1)

        assert (restored.code, restored.code_parts, restored.code_version) == ("CODE v1", {"v": 1}, 3)
        kept = LessonVersion.objects.get(lesson=lesson, code_version=2)
        assert (kept.code, kept.reason) == ("CODE v2", "Before going back to version 1")
        assert [v.code_version for v in CodeService().versions(lesson)] == [2, 1]

    def test_going_forward_again_works_because_nothing_was_lost(self, make_lesson):
        lesson = self.versioned(make_lesson)
        service = CodeService()
        service.restore(lesson, 1)

        again = service.restore(lesson, 2)

        assert (again.code, again.code_version) == ("CODE v2", 4)

    def test_the_current_version_and_unknown_versions_are_not_found(self, make_lesson):
        lesson = self.versioned(make_lesson)

        for number in (2, 9):
            with pytest.raises(VersionNotFound):
                CodeService().restore(lesson, number)

    def test_a_lesson_that_is_not_ready_or_is_being_worked_on_is_refused(self, make_lesson):
        lesson = self.versioned(make_lesson)
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED)
        with pytest.raises(WrongStage):
            CodeService().restore(lesson, 1)

        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)
        GraphRun.objects.create(lesson=lesson, graph="runtime_repair", trigger="repair", status="running")
        with pytest.raises(RunInProgress):
            CodeService().restore(lesson, 1)


FINAL_TEST = make_final_test()
TEST_IDS = {q["type"]: q["id"] for q in FINAL_TEST["questions"]}
MCQ, MSQ, NUM, SHORT, LONG = (TEST_IDS[t] for t in ("mcq", "msq", "numerical", "short_answer", "long_answer"))
MARKS = {q["id"]: q["marks"] for q in FINAL_TEST["questions"]}


def first_submission(queue, lesson, answers):
    """Attempt 1 started and handed in at once → (the attempt, the grading run if some answers need a judge)."""
    service = AttemptService(queue=queue)
    return service.submit(lesson, service.start(lesson).attempt.id, answers)


def lesson_with_test(make_lesson, **fields):
    return ready_lesson(make_lesson, **({"final_test": FINAL_TEST} | fields))


class TestSubmitLessonTest:
    def test_the_automatic_answers_are_marked_at_once_and_the_open_ones_queued_for_grading(self, make_lesson, queue):
        lesson = lesson_with_test(make_lesson)

        submission, run = first_submission(
            queue, lesson, {MCQ: 1, NUM: "4", SHORT: "Halve it.", LONG: "Keep the invariant."}
        )

        assert submission.status == TestSubmission.Status.GRADING and submission.graded_at is None
        assert submission.result["complete"] is False
        assert submission.result["score"]["awarded"] == MARKS[MCQ] + MARKS[NUM]
        assert (run.graph, run.trigger) == (GraphRun.Graph.GRADE_TEST, GraphRun.Trigger.GRADE)
        assert run.payload == {"input": {"submission_id": str(submission.id)}} and queue.runs == [run]

    def test_with_nothing_to_grade_the_result_is_final_and_nothing_is_queued(self, make_lesson, queue):
        lesson = lesson_with_test(make_lesson)

        submission, run = first_submission(queue, lesson, {MCQ: 1, NUM: "9", SHORT: "  "})

        assert run is None and queue.runs == []
        assert submission.status == TestSubmission.Status.GRADED and submission.graded_at is not None
        assert submission.result["complete"] is True and submission.result["score"]["awarded"] == MARKS[MCQ]

    def test_a_multiple_select_answer_is_a_list_of_options_and_earns_partial_marks(self, make_lesson, queue):
        lesson = lesson_with_test(make_lesson)
        msq = next(q for q in FINAL_TEST["questions"] if q["id"] == MSQ)  # options 0 and 2 are right

        submission, _ = first_submission(queue, lesson, {MSQ: [0]})

        assert submission.answers[MSQ] == [0]
        assert submission.result["score"]["awarded"] == msq["marks"] - 1  # half of the right options: full minus 1

    @pytest.mark.parametrize("bad", [["a"], [True], [1.5], list(range(13)), [[0]]])
    def test_a_list_that_is_not_a_short_list_of_option_numbers_is_refused(self, make_lesson, queue, bad):
        with pytest.raises(InvalidAnswers, match="short list of option numbers"):
            first_submission(queue, lesson_with_test(make_lesson), {MSQ: bad})

        assert TestSubmission.objects.get().status == TestSubmission.Status.IN_PROGRESS  # nothing was sealed

    def test_an_empty_submission_is_a_zero_not_an_error(self, make_lesson, queue):
        submission, run = first_submission(queue, lesson_with_test(make_lesson), {})

        assert run is None and submission.result["score"]["awarded"] == 0

    @pytest.mark.parametrize(
        ("answers", "message"),
        [
            (["x"], "object of question id"),
            ({"nope": 1}, "Unknown question ids: nope"),
            ({MCQ: True}, "must be a number or text"),
            ({SHORT: ["a"]}, "short list of option numbers"),
            ({SHORT: {"a": 1}}, "must be a number or text"),
            ({SHORT: "x" * 10_001}, "longer than 10000"),
        ],
    )
    def test_answers_that_do_not_fit_are_refused_and_nothing_is_stored(self, make_lesson, queue, answers, message):
        with pytest.raises(InvalidAnswers, match=message):
            first_submission(queue, lesson_with_test(make_lesson), answers)

        attempt = TestSubmission.objects.get()
        assert (attempt.status, attempt.answers) == (TestSubmission.Status.IN_PROGRESS, {}) and queue.runs == []

    @pytest.mark.parametrize("fields", [{"stage": Stage.GENERATING_LESSON}, {"final_test": {}}, {"final_test": None}])
    def test_a_lesson_without_a_test_to_take_is_refused(self, make_lesson, queue, fields):
        lesson = ready_lesson(make_lesson, **({"final_test": FINAL_TEST} | fields))

        with pytest.raises(WrongStage):
            first_submission(queue, lesson, {MCQ: 1})

    def test_another_lessons_attempt_does_not_count(self, make_lesson, queue):
        TestSubmission.objects.create(lesson=lesson_with_test(make_lesson))

        submission, _ = first_submission(queue, lesson_with_test(make_lesson), {MCQ: 1})

        assert submission.status == TestSubmission.Status.GRADED

    def test_a_mastery_lesson_has_no_test_to_take(self, make_lesson, queue):
        lesson = lesson_with_test(make_lesson, route="mastery")

        with pytest.raises(WrongStage):
            first_submission(queue, lesson, {MCQ: 1})

    def test_a_repair_in_progress_does_not_block_a_submission(self, make_lesson, queue):
        lesson = lesson_with_test(make_lesson)
        GraphRun.objects.create(lesson=lesson, graph="runtime_repair", trigger="repair", status="running")

        submission, _ = first_submission(queue, lesson, {MCQ: 1})

        assert submission.result["score"]["awarded"] == MARKS[MCQ]


class TestGetSubmission:
    def test_it_returns_the_lessons_own_submission(self, make_lesson):
        lesson = lesson_with_test(make_lesson)
        submission = TestSubmission.objects.create(lesson=lesson)

        assert AttemptService().get(lesson, submission.id) == submission

    @pytest.mark.parametrize("wrong", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
    def test_an_unknown_id_is_not_found(self, make_lesson, wrong):
        with pytest.raises(SubmissionNotFound):
            AttemptService().get(lesson_with_test(make_lesson), wrong)

    def test_another_lessons_submission_is_not_found(self, make_lesson):
        theirs = TestSubmission.objects.create(lesson=lesson_with_test(make_lesson))

        with pytest.raises(SubmissionNotFound):
            AttemptService().get(lesson_with_test(make_lesson), theirs.id)


class TestGradingStops:
    def test_a_grading_run_that_cannot_be_queued_fails_its_submission(self, make_lesson):
        lesson = lesson_with_test(make_lesson)

        with pytest.raises(QueueUnavailable):
            first_submission(TestDispatcher.BrokenQueue(), lesson, {SHORT: "Halve it."})

        submission = TestSubmission.objects.get(lesson=lesson)
        assert submission.status == "failed" and "queue" in submission.error
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY  # a ready lesson stays usable

    def test_cancelling_a_grading_run_fails_its_submission_and_not_the_lesson(self, make_lesson, queue):
        lesson = lesson_with_test(make_lesson)
        submission, run = first_submission(queue, lesson, {SHORT: "Halve it."})

        LessonService(queue=queue).cancel(run)

        submission.refresh_from_db()
        assert submission.status == "failed" and "Cancelled" in submission.error
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY


class TestLearnerTest:
    SECRETS = ("correct_index", "correct_indices", "answer", "answer_expr", "tolerance", "model_answer", "criteria",
               "key_points", "rubric", "reference_solution", "test_cases", "concept", "difficulty")  # fmt: skip

    def started(self, make_lesson):
        lesson = lesson_with_test(make_lesson)
        AttemptService().start(lesson)
        return lesson

    def test_the_questions_come_without_answers_marking_schemes_or_concepts(self, make_lesson):
        body = AttemptService().for_learner(self.started(make_lesson))

        by_id = {q["id"]: q for q in body["questions"]}
        assert list(by_id) == [q["id"] for q in FINAL_TEST["questions"]]
        assert not [key for q in body["questions"] for key in self.SECRETS if key in q]
        assert set(by_id[MCQ]) == {"id", "type", "question", "options", "marks"}
        assert set(by_id[MSQ]) == {"id", "type", "question", "options", "marks"}
        assert (by_id[NUM]["unit"], by_id[NUM]["decimal_precision"]) == ("steps", 0)
        assert set(by_id[LONG]) == {"id", "type", "question", "marks"}

    def test_the_total_is_the_sum_of_the_marks(self, make_lesson):
        body = AttemptService().for_learner(self.started(make_lesson))

        assert body["total_marks"] == sum(q["marks"] for q in FINAL_TEST["questions"])

    def test_before_an_attempt_there_are_no_questions_and_the_next_attempt_is_the_first(self, make_lesson):
        body = AttemptService().for_learner(lesson_with_test(make_lesson))

        assert body["submission"] is None and body["attempt"] is None and body["questions"] == []
        assert body["next_attempt_no"] == 1 and body["total_marks"] == 0

    def test_after_a_submission_it_is_named_with_its_status(self, make_lesson, queue):
        lesson = lesson_with_test(make_lesson)
        submission, _ = first_submission(queue, lesson, {SHORT: "Halve it."})

        named = AttemptService().for_learner(lesson)["submission"]

        assert (named["id"], named["status"], named["submitted_at"]) == (
            str(submission.id), "grading", submission.submitted_at,
        )  # fmt: skip
        assert named["attempt_no"] == 1

    @pytest.mark.parametrize(
        "fields",
        [{"stage": Stage.GENERATING_LESSON}, {"final_test": None}, {"final_test": {}}, {"route": "mastery"}],
    )
    def test_a_lesson_that_is_not_ready_or_has_no_test_is_refused(self, make_lesson, fields):
        with pytest.raises(WrongStage):
            AttemptService().for_learner(lesson_with_test(make_lesson, **fields))


class TestCurrentSubmission:
    def test_it_is_the_lessons_one_submission(self, make_lesson):
        lesson = lesson_with_test(make_lesson)
        submission = TestSubmission.objects.create(lesson=lesson)

        assert AttemptService().current(lesson) == submission

    def test_without_a_submission_it_is_not_found(self, make_lesson):
        with pytest.raises(SubmissionNotFound):
            AttemptService().current(lesson_with_test(make_lesson))


class TestRegrade:
    def failed(self, make_lesson, **fields):
        lesson = lesson_with_test(make_lesson)
        submission = TestSubmission.objects.create(
            lesson=lesson, answers={SHORT: "Halve it."}, result={"complete": False}, error="model down",
            status=TestSubmission.Status.FAILED, **fields,
        )  # fmt: skip
        return lesson, submission

    def test_a_failed_grading_runs_again_on_the_same_stored_answers(self, make_lesson, queue):
        lesson, submission = self.failed(make_lesson)

        run = AttemptService(queue=queue).regrade(lesson, submission.id)

        submission.refresh_from_db()
        assert (submission.status, submission.error, submission.answers) == ("grading", "", {SHORT: "Halve it."})
        assert (run.graph, run.trigger) == (GraphRun.Graph.GRADE_TEST, GraphRun.Trigger.GRADE)
        assert run.payload == {"input": {"submission_id": str(submission.id)}} and queue.runs == [run]
        assert TestSubmission.objects.filter(lesson=lesson).count() == 1

    @pytest.mark.parametrize("status", [TestSubmission.Status.GRADING, TestSubmission.Status.GRADED])
    def test_a_submission_that_has_not_failed_is_not_regraded(self, make_lesson, queue, status):
        lesson = lesson_with_test(make_lesson)
        submission = TestSubmission.objects.create(lesson=lesson, status=status)

        with pytest.raises(NotFailed):
            AttemptService(queue=queue).regrade(lesson, submission.id)

        submission.refresh_from_db()
        assert submission.status == status and queue.runs == []

    def test_it_waits_for_a_run_that_is_still_going(self, make_lesson, queue):
        lesson, submission = self.failed(make_lesson)
        GraphRun.objects.create(lesson=lesson, graph="grade_test", trigger="grade", status="running")

        with pytest.raises(RunInProgress):
            AttemptService(queue=queue).regrade(lesson, submission.id)

        submission.refresh_from_db()
        assert submission.status == "failed" and queue.runs == []

    def test_another_lessons_submission_is_not_found(self, make_lesson, queue):
        _, theirs = self.failed(make_lesson)

        with pytest.raises(SubmissionNotFound):
            AttemptService(queue=queue).regrade(lesson_with_test(make_lesson), theirs.id)

    def test_a_run_that_cannot_be_queued_fails_the_submission_again(self, make_lesson):
        lesson, submission = self.failed(make_lesson)

        with pytest.raises(QueueUnavailable):
            AttemptService(queue=TestDispatcher.BrokenQueue()).regrade(lesson, submission.id)

        submission.refresh_from_db()
        assert submission.status == "failed" and "queue" in submission.error

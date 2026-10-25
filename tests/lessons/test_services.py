"""Unit under test: `lessons.services.LessonService` and `QuizService`, the use cases behind the lessons API.

Why: these decide what may happen to a lesson. Starting one snapshots the model registry and settings, so an admin edit
never changes a lesson mid-flight; a quiz may be answered once, only when the lesson is waiting for it, and its answers
must be complete. Getting any of that wrong either corrupts a lesson's flow or lets a learner replay a diagnostic.

Use cases:
- creating a lesson snapshots the registry and the flow settings, queues a start run and enqueues it
- creating a lesson refuses when no model is bound for the first step, and leaves nothing behind
- retrying a failed lesson queues a retry run; any other stage, or a run in progress, is refused
- deleting a lesson cancels its active runs and removes it with everything attached
- an unreachable queue fails the run and the lesson, so Retry works once it is back
- the learner's quiz has no answers, explanations or concepts
- a quiz that does not exist yet is not found
- submitting grades the quiz, stores the attempt, queues a resume run and returns the score with the route
- submitting the prerequisite quiz returns a score without a route
- submitting is refused when the lesson is not waiting for that quiz, was already answered, or a run is active
- incomplete or invalid answers are refused with the reason, and nothing is stored
- reviewing shows the learner's answers next to the correct ones, only after an attempt
- choosing a sheet resumes the flow, only while the lesson waits for the choice and with no run active
- an extra sheet can be requested for a ready mastery lesson, once per kind, in its own graph
- a sheet is served with its practice solutions hidden until revealed (by id, several ids or all)
- a practice sheet is graded on submit: multiple choice and numerical are marked, the rest show their solution
- the kinds of sheet a lesson has are listed
- the document is served for a ready lesson only
- a crash report queues a runtime repair and counts against the cap; a stale version, the cap, a lesson that is not
  ready and a run in progress are refused, and nothing is queued
- an earlier version can be restored: the code being replaced is kept, the restored code gets a new code_version, and
  an unknown version, a lesson that is not ready or a run in progress are refused
"""

import pytest
from support.quiz_data import make_prerequisites, make_questions
from support.study_data import make_cheat_sheet, make_practice_sheet, make_revision_sheet

from lessons.errors import (
    AlreadyAttempted,
    AlreadyExists,
    InvalidAnswers,
    LessonNotConfigured,
    MaterialNotFound,
    NotAttempted,
    QueueUnavailable,
    QuizNotFound,
    RepairLimitReached,
    RunInProgress,
    StaleCodeVersion,
    VersionNotFound,
    WrongStage,
)
from lessons.models import FlowSettings, GraphRun, Lesson, LessonVersion, Quiz, QuizAttempt, Stage, StudyMaterial
from lessons.services import CodeService, LessonService, MaterialService, QuizService, RunDispatcher

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


class TestRetry:
    def test_a_failed_lesson_gets_a_retry_run(self, make_lesson, queue):
        lesson = make_lesson(stage=Stage.FAILED, error="boom")

        run = LessonService(queue=queue).retry(lesson)

        assert (run.trigger, run.status, run.graph) == (
            GraphRun.Trigger.RETRY, GraphRun.Status.QUEUED, GraphRun.Graph.FLOW,
        )  # fmt: skip
        assert queue.runs == [run]

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
    def test_resumes_the_flow_with_the_chosen_kind(self, make_lesson, queue):
        lesson = mastery_lesson(make_lesson)

        run = MaterialService(queue=queue).choose(lesson, "cheat_sheet")

        assert (run.graph, run.trigger, run.payload) == (
            GraphRun.Graph.FLOW, GraphRun.Trigger.RESUME_CHOICE, {"resume": "cheat_sheet"},
        )  # fmt: skip
        assert queue.runs == [run]

    @pytest.mark.parametrize("stage", [Stage.AWAITING_DIAGNOSTIC, Stage.GENERATING_MATERIAL, Stage.READY])
    def test_is_refused_unless_the_lesson_waits_for_the_choice(self, make_lesson, queue, stage):
        with pytest.raises(WrongStage):
            MaterialService(queue=queue).choose(mastery_lesson(make_lesson, stage), "cheat_sheet")

        assert queue.runs == []

    def test_is_refused_while_a_run_is_active(self, make_lesson, queue):
        lesson = mastery_lesson(make_lesson)
        GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.RUNNING)

        with pytest.raises(RunInProgress):
            MaterialService(queue=queue).choose(lesson, "cheat_sheet")


class TestRequestExtra:
    def test_queues_the_study_material_graph_with_its_input(self, make_lesson, queue):
        lesson = mastery_lesson(make_lesson, Stage.READY)

        run = MaterialService(queue=queue).request_extra(lesson, "revision_sheet")

        assert (run.graph, run.trigger) == (GraphRun.Graph.STUDY_MATERIAL, GraphRun.Trigger.EXTRA_MATERIAL)
        assert run.payload == {"input": {"mastery_choice": "revision_sheet", "extra_material": True}}
        assert queue.runs == [run]

    def test_a_kind_the_lesson_already_has_is_refused(self, make_lesson, queue):
        lesson = mastery_lesson(make_lesson, Stage.READY)
        StudyMaterial.objects.create(lesson=lesson, kind="cheat_sheet", content=make_cheat_sheet())

        with pytest.raises(AlreadyExists):
            MaterialService(queue=queue).request_extra(lesson, "cheat_sheet")

    @pytest.mark.parametrize(
        ("stage", "route"),
        [(Stage.AWAITING_CHOICE, "mastery"), (Stage.GENERATING_LESSON, "lesson"), (Stage.READY, "lesson")],
    )
    def test_only_a_ready_mastery_lesson_can_get_more_sheets(self, make_lesson, queue, stage, route):
        with pytest.raises(WrongStage):
            MaterialService(queue=queue).request_extra(make_lesson(stage=stage, route=route), "cheat_sheet")

    def test_one_extra_sheet_at_a_time(self, make_lesson, queue):
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
        assert by_id["t1"]["correct"] is True and by_id["t1"]["awarded"] == 2
        assert by_id["t2"]["correct"] is True
        assert by_id["t3"]["correct"] is None and by_id["t3"]["solution"]["model_answer"] == "Halve the range."
        assert by_id["t4"]["correct"] is False and by_id["t4"]["solution"]["correct_index"] == 0
        assert result["score"]["awarded"] == 4 and result["score"]["open_marks"] == 10

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

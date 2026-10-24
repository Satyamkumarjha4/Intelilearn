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
"""

import pytest
from support.quiz_data import make_prerequisites, make_questions

from lessons.errors import (
    AlreadyAttempted,
    InvalidAnswers,
    LessonNotConfigured,
    NotAttempted,
    QueueUnavailable,
    QuizNotFound,
    RunInProgress,
    WrongStage,
)
from lessons.models import FlowSettings, GraphRun, Lesson, Quiz, QuizAttempt, Stage
from lessons.services import LessonService, QuizService, RunDispatcher

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

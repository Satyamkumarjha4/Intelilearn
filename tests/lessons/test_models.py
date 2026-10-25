"""Unit under test: the `lessons` domain: `StageTransitions`, `Lesson` (`advance_to`, `fail`, `LessonQuerySet`),
`Quiz.public_questions`, `GraphRun.is_active`, `FlowSettings` and the table constraints.

Why: the stage drives what the learner sees and which actions are allowed. An illegal jump (a finished lesson back to
a quiz) or a query that forgets the owner filter shows a learner the wrong screen or another learner's lessons. The
quiz questions are the only thing sent to the browser before submission, so the answers must never be in them.

Use cases:
- advance_to saves a legal move, clears a previous error, and writes the extra fields given
- advance_to refuses an illegal move and leaves the stored lesson untouched
- advance_to to the current stage is allowed (a node that re-runs on retry)
- fail records a readable error and moves the lesson to failed, except from ready
- a retry can leave failed for the stage the failed node belongs to
- owned_by returns only the user's lessons, and active() excludes finished ones
- public_questions strips the correct answer, explanation and concept from every question
- a lesson has at most one quiz of each kind, and a quiz at most one attempt
- GraphRun.is_active is true only while queued or running
- a test submission starts as grading and goes with its lesson
- a lesson has at most one test submission
- FlowSettings is a singleton with the documented defaults, and snapshots to plain JSON
"""

import pytest
from django.db import IntegrityError, transaction

from lessons.models import FlowSettings, GraphRun, Lesson, Quiz, QuizAttempt, Stage, TestSubmission
from lessons.stages import IllegalTransition


class TestLessonStage:
    def test_advance_to_saves_a_legal_move(self, lesson):
        lesson.advance_to(Stage.AWAITING_DIAGNOSTIC)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_DIAGNOSTIC
        assert lesson.stage == Stage.AWAITING_DIAGNOSTIC

    def test_advance_to_clears_an_earlier_error_and_writes_the_extra_fields(self, lesson):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED, error="boom")
        lesson.refresh_from_db()

        lesson.advance_to(Stage.GENERATING_LESSON, route="lesson", prerequisites_to_cover=[{"name": "x"}])

        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.error, stored.route, stored.prerequisites_to_cover) == ("", "lesson", [{"name": "x"}])

    def test_advance_to_refuses_an_illegal_move_and_leaves_the_lesson_alone(self, lesson):
        with pytest.raises(IllegalTransition, match="preparing_diagnostic.*ready"):
            lesson.advance_to(Stage.READY, title="nope")

        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, stored.title) == (Stage.PREPARING_DIAGNOSTIC, "")

    def test_advance_to_judges_the_move_by_the_stored_stage_not_a_stale_copy(self, lesson):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)  # changed elsewhere, e.g. another worker

        with pytest.raises(IllegalTransition):
            lesson.advance_to(Stage.AWAITING_DIAGNOSTIC)

    def test_advance_to_the_current_stage_is_allowed(self, lesson):
        lesson.advance_to(Stage.PREPARING_DIAGNOSTIC, title="again")

        assert Lesson.objects.get(pk=lesson.pk).title == "again"

    def test_fail_records_the_error_and_moves_to_failed(self, lesson):
        lesson.fail("The model refused.")

        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, stored.error) == (Stage.FAILED, "The model refused.")

    def test_fail_does_not_spoil_a_finished_lesson(self, lesson):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)
        lesson.refresh_from_db()

        lesson.fail("a later extra sheet failed")

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY

    def test_record_updates_fields_without_changing_the_stage(self, lesson):
        lesson.record(title="Binary search", level="beginner")

        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.title, stored.level, stored.stage) == ("Binary search", "beginner", Stage.PREPARING_DIAGNOSTIC)


class TestLessonQuerySet:
    def test_owned_by_returns_only_that_users_lessons(self, make_lesson, user, other_user):
        mine = make_lesson(topic="mine")
        make_lesson(topic="theirs", owner=other_user)

        assert list(Lesson.objects.owned_by(user)) == [mine]

    def test_active_excludes_finished_and_failed_lessons(self, make_lesson):
        working = make_lesson(topic="working", stage=Stage.GENERATING_LESSON)
        make_lesson(topic="done", stage=Stage.READY)
        make_lesson(topic="broken", stage=Stage.FAILED)

        assert list(Lesson.objects.active()) == [working]

    def test_owned_by_can_be_chained_with_other_filters(self, make_lesson, user):
        make_lesson(topic="a", stage=Stage.READY)
        make_lesson(topic="b")

        assert [lesson.topic for lesson in Lesson.objects.owned_by(user).active()] == ["b"]


QUESTION = {
    "id": "q1",
    "band": "basic",
    "concept": "Searching a list",
    "question": "What is binary search?",
    "options": ["a", "b", "c", "d"],
    "correct_index": 2,
    "explanation": "Because.",
}
PREREQUISITE_QUESTION = {
    "id": "p1",
    "prerequisite": "Arrays",
    "question": "What is an array?",
    "options": ["a", "b", "c", "d"],
    "correct_index": 0,
    "explanation": "Because.",
}


class TestQuiz:
    def test_public_questions_strip_the_answer_the_explanation_and_the_concept(self, lesson):
        quiz = Quiz.objects.create(lesson=lesson, kind=Quiz.Kind.DIAGNOSTIC, questions=[QUESTION])

        assert quiz.public_questions() == [
            {"id": "q1", "band": "basic", "question": "What is binary search?", "options": ["a", "b", "c", "d"]}
        ]

    def test_public_questions_of_a_prerequisite_quiz_have_no_band_or_prerequisite_name(self, lesson):
        quiz = Quiz.objects.create(lesson=lesson, kind=Quiz.Kind.PREREQUISITE, questions=[PREREQUISITE_QUESTION])

        assert quiz.public_questions() == [
            {"id": "p1", "question": "What is an array?", "options": ["a", "b", "c", "d"]}
        ]

    def test_a_lesson_has_at_most_one_quiz_of_each_kind(self, lesson):
        Quiz.objects.create(lesson=lesson, kind=Quiz.Kind.DIAGNOSTIC, questions=[])

        with pytest.raises(IntegrityError), transaction.atomic():
            Quiz.objects.create(lesson=lesson, kind=Quiz.Kind.DIAGNOSTIC, questions=[])

        Quiz.objects.create(lesson=lesson, kind=Quiz.Kind.PREREQUISITE, questions=[])

    def test_a_quiz_has_at_most_one_attempt(self, lesson):
        quiz = Quiz.objects.create(lesson=lesson, kind=Quiz.Kind.DIAGNOSTIC, questions=[])
        QuizAttempt.objects.create(quiz=quiz, answers={}, result={})

        with pytest.raises(IntegrityError), transaction.atomic():
            QuizAttempt.objects.create(quiz=quiz, answers={}, result={})


class TestGraphRun:
    @pytest.mark.parametrize(
        ("status", "active"),
        [
            (GraphRun.Status.QUEUED, True),
            (GraphRun.Status.RUNNING, True),
            (GraphRun.Status.PAUSED, False),
            (GraphRun.Status.SUCCEEDED, False),
            (GraphRun.Status.FAILED, False),
            (GraphRun.Status.CANCELLED, False),
        ],
        ids=lambda v: str(getattr(v, "value", v)),
    )
    def test_is_active_only_while_queued_or_running(self, lesson, status, active):
        run = GraphRun(lesson=lesson, trigger=GraphRun.Trigger.START, status=status)

        assert run.is_active is active

    def test_terminal_statuses_are_the_ones_that_end_a_stream(self):
        assert GraphRun.TERMINAL == {
            GraphRun.Status.PAUSED,
            GraphRun.Status.SUCCEEDED,
            GraphRun.Status.FAILED,
            GraphRun.Status.CANCELLED,
        }


class TestFlowSettings:
    def test_load_creates_one_row_with_the_documented_defaults(self, db):
        settings = FlowSettings.load()

        assert FlowSettings.objects.count() == 1
        assert (settings.diagnostic_questions_per_band, settings.prereq_trigger_max_correct) == (2, 2)
        assert (settings.final_test_min, settings.final_test_max) == (10, 15)
        assert settings.media_sources == ["wikimedia", "openverse"]

    def test_saving_another_instance_still_leaves_a_single_row(self, db):
        FlowSettings.load()

        FlowSettings(prereq_trigger_max_correct=1).save()

        assert FlowSettings.objects.count() == 1
        assert FlowSettings.load().prereq_trigger_max_correct == 1

    def test_snapshot_is_plain_json_of_every_setting(self, db):
        snapshot = FlowSettings.load().snapshot()

        assert snapshot["alignment_min_score"] == 3
        assert "id" not in snapshot
        assert snapshot["allowed_media_licenses"] == ["cc0", "pdm", "cc-by", "cc-by-sa"]


def test_a_test_submission_starts_as_grading_and_goes_with_its_lesson(lesson):
    submission = TestSubmission.objects.create(lesson=lesson, answers={"t1": 1})

    assert submission.status == TestSubmission.Status.GRADING and submission.result is None
    assert submission.graded_at is None and str(submission) == "Test of Binary search (Grading)"
    assert list(lesson.submissions.all()) == [submission]
    lesson.delete()
    assert not TestSubmission.objects.exists()


def test_a_lesson_has_at_most_one_test_submission(lesson, make_lesson):
    TestSubmission.objects.create(lesson=lesson)

    with pytest.raises(IntegrityError), transaction.atomic():
        TestSubmission.objects.create(lesson=lesson)

    TestSubmission.objects.create(lesson=make_lesson())  # another lesson is not affected
    assert TestSubmission.objects.count() == 2

"""Unit under test: `quizzes.models` (`QuickQuiz`, `QuickQuizSource`, `QuickQuizAttempt`): the data of a quick quiz.

Why: a quiz is its own aggregate, not a lesson. It must satisfy the run port so the runner, Stop and the console treat
it like a lesson, its settings must never change after it is made (attempts are compared by them), one attempt may be
open at a time, and an attempt is sealed by the same rule as a lesson's test attempt. A lesson that a quiz was made
from can be deleted without taking the quiz's questions with it.

Use cases:
- a quiz satisfies the `RunSubject` port and starts in the `preparing` stage with nothing assessed
- `advance_to` moves it along the table and refuses an illegal move; `fail` marks a quiz that is still being made as
  failed and leaves a ready quiz alone (a failed retake must not lose the quiz); `record` writes only what it is given
- the settings (source type, topic, config, hash) are fixed once the quiz exists: saving a change, or recording one, is
  refused
- the quiz's level is the one in its assessment, or empty before it is known
- a source row says which lesson, at what level, how many questions; a lesson is a source of a quiz once; a deleted
  lesson leaves the row (with the lesson's title) so the quiz keeps its shares
- attempts are numbered per quiz, at most one is open at a time, and the newest comes first
- an attempt is sealed once: answers, score and band are written, and a second seal is refused
- deleting a quiz deletes its sources and attempts
"""

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from lessons.errors import AttemptSealed
from lessons.subjects import RunSubject
from quizzes.models import QuickQuiz, QuickQuizAttempt, QuickQuizSource
from quizzes.stages import QuizStage

pytestmark = pytest.mark.django_db


class TestQuickQuiz:
    def test_it_satisfies_the_run_port(self, quiz):
        assert isinstance(quiz, RunSubject)

    def test_it_starts_preparing_with_nothing_assessed(self, user):
        made = QuickQuiz.objects.create(
            owner=user, source_type="topic", topic="x", config={"num_questions": 5}, config_hash="h"
        )

        assert made.stage == QuizStage.PREPARING and made.assessment is None and made.calibration is None
        assert made.config_snapshot == {} and made.settings_snapshot == {} and made.error == ""

    def test_a_legal_move_is_made_and_clears_the_error(self, make_quiz):
        quiz = make_quiz(stage=QuizStage.PREPARING, error="old")

        quiz.advance_to(QuizStage.AWAITING_CALIBRATION)

        quiz.refresh_from_db()
        assert quiz.stage == QuizStage.AWAITING_CALIBRATION and quiz.error == ""

    def test_an_illegal_move_is_refused(self, quiz):
        with pytest.raises(Exception, match="cannot go from ready to awaiting_calibration"):
            quiz.advance_to(QuizStage.AWAITING_CALIBRATION)

    def test_the_move_is_judged_against_the_database_not_this_copy(self, make_quiz):
        quiz = make_quiz(stage=QuizStage.PREPARING)
        QuickQuiz.objects.filter(pk=quiz.pk).update(stage=QuizStage.READY)

        with pytest.raises(Exception, match="cannot go from ready"):
            quiz.advance_to(QuizStage.AWAITING_CALIBRATION)

    def test_a_quiz_that_is_being_made_can_fail(self, make_quiz):
        quiz = make_quiz(stage=QuizStage.PREPARING)

        quiz.fail("The questions could not be written.")

        quiz.refresh_from_db()
        assert (quiz.stage, quiz.error) == (QuizStage.FAILED, "The questions could not be written.")

    def test_a_ready_quiz_stays_ready_when_a_retake_fails(self, quiz):
        quiz.fail("The questions could not be written.")

        quiz.refresh_from_db()
        assert quiz.stage == QuizStage.READY and quiz.error == ""

    def test_record_writes_only_what_it_is_given(self, quiz):
        QuickQuiz.objects.filter(pk=quiz.pk).update(error="other process")

        quiz.record(assessment={"level": "foundation"})

        quiz.refresh_from_db()
        assert quiz.assessment == {"level": "foundation"} and quiz.error == "other process"

    @pytest.mark.parametrize("field", ["config", "config_hash", "source_type", "topic", "owner_id"])
    def test_recording_a_setting_is_refused(self, quiz, field):
        with pytest.raises(ValueError, match="cannot change"):
            quiz.record(**{field: "changed"})

    def test_saving_a_changed_config_is_refused(self, quiz):
        quiz.config = {**quiz.config, "num_questions": 30}

        with pytest.raises(ValueError, match="cannot change"):
            quiz.save()

    def test_saving_something_else_is_fine(self, quiz):
        quiz.error = "x"
        quiz.save()

        assert QuickQuiz.objects.get(pk=quiz.pk).error == "x"

    def test_the_level_is_the_assessments(self, quiz):
        assert quiz.level == ""
        quiz.record(assessment={"level": "proficient", "level_scheme": 2})
        assert quiz.level == "proficient"

    def test_it_is_a_topic_or_lessons_quiz(self):
        assert set(QuickQuiz.SourceType.values) == {"topic", "lessons"}


class TestSources:
    def test_a_source_row_has_the_lesson_its_level_and_its_share(self, quiz, lesson):
        source = QuickQuizSource.objects.create(
            quiz=quiz, lesson=lesson, lesson_ref=lesson.pk, title=lesson.topic, level="foundation", share=4
        )

        assert (source.quiz, source.lesson, source.level, source.share) == (quiz, lesson, "foundation", 4)
        assert list(quiz.sources.all()) == [source]

    def test_a_lesson_is_a_source_of_a_quiz_once(self, quiz, lesson):
        QuickQuizSource.objects.create(
            quiz=quiz, lesson=lesson, lesson_ref=lesson.pk, title="t", level="foundation", share=4
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            QuickQuizSource.objects.create(
                quiz=quiz, lesson=lesson, lesson_ref=lesson.pk, title="t", level="expert", share=1
            )

    def test_a_deleted_lesson_leaves_the_row_with_its_title(self, quiz, lesson):
        source = QuickQuizSource.objects.create(
            quiz=quiz, lesson=lesson, lesson_ref=lesson.pk, title="Binary search", level="beginner", share=3
        )

        lesson.delete()

        source.refresh_from_db()
        assert source.lesson is None and source.title == "Binary search" and source.share == 3

    def test_two_lessons_deleted_do_not_clash_on_the_unique_constraint(self, quiz, make_lesson):
        for _ in range(2):
            lesson = make_lesson()
            QuickQuizSource.objects.create(
                quiz=quiz, lesson=lesson, lesson_ref=lesson.pk, title="t", level="beginner", share=1
            )
            lesson.delete()

        assert quiz.sources.count() == 2


class TestAttempts:
    def test_attempts_are_numbered_per_quiz(self, make_quiz, make_attempt):
        one, other = make_quiz(), make_quiz(topic="Sorting")

        make_attempt(one, status="graded")
        make_attempt(other, status="graded")

        assert [a.attempt_no for a in QuickQuizAttempt.objects.filter(quiz=one)] == [1]

    def test_an_attempt_number_is_used_once_per_quiz(self, quiz, make_attempt):
        make_attempt(quiz, status="graded")

        with pytest.raises(IntegrityError), transaction.atomic():
            make_attempt(quiz, attempt_no=1, status="graded")

    @pytest.mark.parametrize("status", ["generating", "in_progress"])
    def test_only_one_attempt_is_open_at_a_time(self, quiz, make_attempt, status):
        make_attempt(quiz, status=status)

        with pytest.raises(IntegrityError), transaction.atomic():
            make_attempt(quiz, status="in_progress")

    def test_a_graded_attempt_does_not_stop_another_from_opening(self, quiz, make_attempt):
        make_attempt(quiz, status="graded")

        assert make_attempt(quiz, status="in_progress").is_open

    def test_the_newest_attempt_comes_first(self, quiz, make_attempt):
        make_attempt(quiz, status="graded")
        make_attempt(quiz, status="graded")

        assert [a.attempt_no for a in quiz.attempts.all()] == [2, 1]

    def test_an_attempt_is_sealed_once(self, quiz, make_attempt):
        attempt = make_attempt(quiz, status="in_progress", questions=[{"id": "t1"}])
        card = {"score": {"awarded": 3, "available": 4}}

        attempt.seal(
            answers={"t1": 0}, status="graded", result=card, band="normal", all_blank=False, now=timezone.now()
        )

        assert (attempt.status, attempt.awarded, attempt.available, attempt.band) == ("graded", 3, 4, "normal")
        assert attempt.answers == {"t1": 0} and attempt.submitted_at and attempt.graded_at and attempt.duration_s == 0
        with pytest.raises(AttemptSealed):
            attempt.seal(answers={}, status="graded", result=card, band="fail", all_blank=True, now=timezone.now())

    def test_an_attempt_with_answers_still_to_be_marked_is_not_scored_yet(self, quiz, make_attempt):
        attempt = make_attempt(quiz, status="in_progress")

        attempt.seal(
            answers={}, status="grading", result={"score": {"awarded": 1, "available": 5}}, band="",
            all_blank=False, now=timezone.now(),
        )  # fmt: skip

        assert attempt.status == "grading" and attempt.awarded is None and attempt.graded_at is None

    def test_deleting_a_quiz_deletes_its_attempts_and_sources(self, quiz, make_attempt, lesson):
        make_attempt(quiz, status="graded")
        QuickQuizSource.objects.create(
            quiz=quiz, lesson=lesson, lesson_ref=lesson.pk, title="t", level="beginner", share=1
        )

        quiz.delete()

        assert QuickQuizAttempt.objects.count() == 0 and QuickQuizSource.objects.count() == 0

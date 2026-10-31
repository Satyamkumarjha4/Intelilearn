"""Unit under test: `quizzes.attempts.QuizAttemptService`: answering a quiz one question at a time, sealing the
attempt, and
marking it.

Why: it is the lesson test's attempt machinery on a quiz, so it must keep the same promises: each answer is locked on
the server (forward only), a sealed attempt never changes, a learner never sees a key, and a score is a band from the
quiz's own thresholds. A quiz also holds the written answers a lesson test never has, which a model marks in a
`grade_quiz` run.

Use cases:
- an answer is saved and locks its question; a second answer, an unknown question, a bad shape, and an attempt that is
  still being written or already over are refused
- submitting seals the attempt, fills the missing answers with blanks, and marks it: an attempt of questions with one
  right answer is graded in the request with its band and no run; written answers queue a `grade_quiz` run and leave the
  attempt grading; an attempt of blanks is flagged
- the band uses the quiz's thresholds; the answers sent with the submit fill only unlocked questions
- a second submit, and a late answer, are refused
- the questions are shown without keys (nor the lesson they are about), and none at all before the attempt starts
- the history compares only this quiz's graded attempts
- a failed grading can be graded again, once, and not while a run is going
- another quiz's attempt is not found
"""

import pytest
from support.question_data import make_question

from lessons.errors import (
    AttemptSealed,
    InvalidAnswers,
    NotFailed,
    QuestionLocked,
    RunInProgress,
    SubmissionNotFound,
    WrongStage,
)
from lessons.models import GraphRun
from quizzes.attempts import QuizAttemptService
from quizzes.models import QuickQuiz, QuickQuizAttempt

pytestmark = pytest.mark.django_db

QUESTIONS = [
    make_question("mcq", 1, "easy") | {"source": "lesson-a"},
    make_question("msq", 2, "basic"),
    make_question("numerical", 3, "standard"),
]
RIGHT = {"t1": 1, "t2": [0, 2], "t3": 4}


@pytest.fixture
def service(queue):
    return QuizAttemptService(queue=queue)


@pytest.fixture
def taking(quiz, make_attempt):
    return quiz, make_attempt(quiz, status="in_progress", questions=QUESTIONS)


class TestAnswering:
    def test_an_answer_is_saved_and_locks_its_question(self, service, taking):
        quiz, attempt = taking

        saved = service.save_answer(quiz, attempt.pk, "t1", 1)

        assert saved.answers == {"t1": 1} and QuickQuizAttempt.objects.get(pk=attempt.pk).answers == {"t1": 1}
        with pytest.raises(QuestionLocked):
            service.save_answer(quiz, attempt.pk, "t1", 0)

    def test_a_blank_answer_locks_too(self, service, taking):
        quiz, attempt = taking
        service.save_answer(quiz, attempt.pk, "t1", None)

        with pytest.raises(QuestionLocked):
            service.save_answer(quiz, attempt.pk, "t1", 1)

    @pytest.mark.parametrize("question", ["t9", "", "lesson-a"])
    def test_an_unknown_question_is_refused(self, service, taking, question):
        quiz, attempt = taking

        with pytest.raises(InvalidAnswers):
            service.save_answer(quiz, attempt.pk, question, 1)

    @pytest.mark.parametrize("value", [{"a": 1}, [1.5], True, "x" * 10_001, [1] * 13])
    def test_an_answer_of_the_wrong_shape_is_refused(self, service, taking, value):
        quiz, attempt = taking

        with pytest.raises(InvalidAnswers):
            service.save_answer(quiz, attempt.pk, "t1", value)

    def test_an_attempt_still_being_written_takes_no_answers(self, service, quiz, make_attempt):
        attempt = make_attempt(quiz, status="generating")

        with pytest.raises(WrongStage):
            service.save_answer(quiz, attempt.pk, "t1", 1)

    def test_an_attempt_that_is_over_takes_no_answers(self, service, quiz, make_attempt):
        attempt = make_attempt(quiz, status="graded", questions=QUESTIONS)

        with pytest.raises(AttemptSealed):
            service.save_answer(quiz, attempt.pk, "t1", 1)

    def test_another_quizs_attempt_is_not_found(self, service, taking, make_quiz):
        _, attempt = taking

        with pytest.raises(SubmissionNotFound):
            service.save_answer(make_quiz(topic="Other"), attempt.pk, "t1", 1)

    @pytest.mark.parametrize("attempt_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
    def test_an_id_that_does_not_exist_is_not_found(self, service, quiz, attempt_id):
        with pytest.raises(SubmissionNotFound):
            service.get(quiz, attempt_id)


class TestSubmitting:
    def test_an_objective_attempt_is_graded_in_the_request_with_its_band(self, service, taking, queue):
        quiz, attempt = taking

        sealed, run = service.submit(quiz, attempt.pk, RIGHT)

        assert run is None and queue.runs == []
        assert (sealed.status, sealed.awarded, sealed.available, sealed.band) == ("graded", 5, 5, "excellent")
        assert sealed.result["complete"] is True and sealed.graded_at and sealed.duration_s is not None
        assert sealed.answers == RIGHT and sealed.all_blank is False

    def test_written_answers_queue_grading_and_the_attempt_waits(self, service, quiz, make_attempt, queue):
        attempt = make_attempt(quiz, status="in_progress", questions=[make_question("short_answer", 1), QUESTIONS[0]])

        sealed, run = service.submit(quiz, attempt.pk, {"t1": "Halve the range."})

        assert sealed.status == "grading" and sealed.awarded is None and sealed.band == ""
        assert (run.graph, run.trigger, run.quick_quiz_id) == ("grade_quiz", "grade", quiz.pk)
        assert run.payload == {"input": {"attempt_id": str(attempt.pk)}} and queue.runs == [run]

    def test_a_blank_written_answer_needs_no_judge(self, service, quiz, make_attempt, queue):
        attempt = make_attempt(quiz, status="in_progress", questions=[make_question("short_answer", 1)])

        sealed, run = service.submit(quiz, attempt.pk, {"t1": "  "})

        assert run is None and sealed.status == "graded" and sealed.awarded == 0

    def test_missing_answers_are_blank_and_an_empty_attempt_is_flagged(self, service, taking):
        quiz, attempt = taking

        sealed, _ = service.submit(quiz, attempt.pk, None)

        assert (sealed.awarded, sealed.band, sealed.all_blank) == (0, "fail", True)

    def test_the_answers_sent_with_the_submit_fill_only_unlocked_questions(self, service, taking):
        quiz, attempt = taking
        service.save_answer(quiz, attempt.pk, "t1", 0)  # wrong, and locked

        sealed, _ = service.submit(quiz, attempt.pk, {"t1": 1, "t2": [0, 2], "t3": 4})

        assert sealed.answers["t1"] == 0 and sealed.awarded == 4

    def test_the_band_uses_the_quizs_thresholds(self, service, taking):
        quiz, attempt = taking
        QuickQuiz.objects.filter(pk=quiz.pk).update(
            settings_snapshot={"band_fail_below": 99, "band_excellent_above": 100}
        )
        quiz.refresh_from_db()  # a request reads the quiz afresh

        sealed, _ = service.submit(quiz, attempt.pk, {"t1": 1, "t2": [0, 2]})

        assert sealed.band == "fail"

    def test_a_second_submit_is_refused(self, service, taking):
        quiz, attempt = taking
        service.submit(quiz, attempt.pk, RIGHT)

        with pytest.raises(AttemptSealed):
            service.submit(quiz, attempt.pk, RIGHT)

    def test_an_answer_for_a_question_that_does_not_exist_is_refused_and_seals_nothing(self, service, taking):
        quiz, attempt = taking

        with pytest.raises(InvalidAnswers):
            service.submit(quiz, attempt.pk, {"t9": 1})

        assert QuickQuizAttempt.objects.get(pk=attempt.pk).status == "in_progress"

    def test_an_attempt_still_being_written_cannot_be_submitted(self, service, quiz, make_attempt):
        attempt = make_attempt(quiz, status="generating")

        with pytest.raises(WrongStage):
            service.submit(quiz, attempt.pk, {})


class TestShowing:
    def test_the_questions_have_no_key_and_do_not_say_which_lesson_they_are_about(self, service, taking):
        _, attempt = taking

        shown = service.shown_questions(attempt)

        assert [q["id"] for q in shown] == ["t1", "t2", "t3"]
        assert all(
            set(q)
            <= {"id", "type", "question", "marks", "options", "unit", "decimal_precision", "language", "starter_code"}
            for q in shown
        )

    def test_nothing_is_shown_before_the_attempt_starts_or_after_it_is_over_through_this_door(
        self, service, quiz, make_attempt
    ):
        assert service.shown_questions(make_attempt(quiz, status="generating", questions=[])) == []

    def test_once_it_is_over_the_questions_are_there_for_the_result_and_not_before(self, service, quiz, make_attempt):
        over = make_attempt(quiz, status="graded", questions=QUESTIONS)
        open_ = make_attempt(quiz, status="in_progress", questions=QUESTIONS)

        assert len(service.sealed_questions(over)) == 3 and service.sealed_questions(open_) == []


class TestHistory:
    def test_only_this_quizs_graded_attempts_are_compared(self, service, quiz, make_quiz, make_attempt):
        other = make_quiz(topic="Other")
        make_attempt(quiz, status="graded", awarded=2, available=4)
        make_attempt(quiz, status="graded", awarded=4, available=4)
        make_attempt(quiz, status="in_progress")
        make_attempt(other, status="graded", awarded=1, available=4)

        history = service.history(quiz)

        assert [a["attempt_no"] for a in history["attempts"]] == [1, 2, 3]
        assert [(p.attempt_no, p.percent, p.delta_previous, p.delta_best) for p in history["trend"].series] == [
            (1, 50, None, None), (2, 100, 50, 50),
        ]  # fmt: skip
        assert history["trend"].best_attempt_no == 2

    def test_an_open_attempt_is_found(self, service, quiz, make_attempt):
        make_attempt(quiz, status="graded")
        open_ = make_attempt(quiz, status="generating")

        assert service.open(quiz) == open_


class TestRegrading:
    @pytest.fixture
    def failed(self, quiz, make_attempt):
        return make_attempt(
            quiz, status="failed", questions=[make_question("short_answer", 1)], answers={"t1": "x"}, error="boom"
        )

    def test_a_failed_attempt_is_graded_again_on_its_answers(self, service, quiz, failed, queue):
        run = service.regrade(quiz, failed.pk)

        stored = QuickQuizAttempt.objects.get(pk=failed.pk)
        assert (stored.status, stored.error) == ("grading", "") and stored.answers == {"t1": "x"}
        assert (run.graph, run.quick_quiz_id) == ("grade_quiz", quiz.pk) and queue.runs == [run]

    def test_not_while_a_run_is_going(self, service, quiz, failed):
        GraphRun.objects.create(quick_quiz=quiz, graph="grade_quiz", trigger="grade", status="running")

        with pytest.raises(RunInProgress):
            service.regrade(quiz, failed.pk)

    @pytest.mark.parametrize("status", ["graded", "grading", "in_progress"])
    def test_only_a_failed_one_can_be(self, service, quiz, make_attempt, status):
        attempt = make_attempt(quiz, status=status)

        with pytest.raises(NotFailed):
            service.regrade(quiz, attempt.pk)

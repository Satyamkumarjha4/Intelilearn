"""Unit under test: `quizzes.services.CalibrationService`, the server side of the calibration walk (plan §9.4, §13).

Why: the walk decides a whole quiz's level, so the server owns it. The pool holds the answers, so a learner must be
shown one question at a time with no band, no answer and no hint of what is next; each answer is final; and only the
ladder, never the browser, chooses the next question and the level. After the last answer exactly one run resumes the
quiz, carrying the authorization that is still open.

Use cases:
- the current question is the first of the middle band, shown with its id, text and options only
- an answer is marked on the server, recorded in the walk, and the next question comes from the ladder (harder after a
  right answer, easier after a wrong one, "I don't know" is wrong)
- an answer to any question but the current one is refused; so is a second answer to the same, and an answer on a quiz
  that is not waiting
- after the fifth answer the reply is the level and one resume run is queued with the open authorization carried; a
  sixth answer is refused and no second run appears
- the level of every path is the ladder's table (a walk of all right is an Expert, all wrong a Beginner)
- asking again after the walk is over reports the level, and the learner is never shown the band
"""

import pytest
from support.gates import CountingGate
from support.quiz_data import make_questions

from graph.ladder import AdaptiveLadder
from lessons.errors import WrongStage
from lessons.metering import Authorization, CompletionPoints, MeteredAction
from lessons.models import GraphRun
from quizzes.errors import NoQuestionLeft, NotTheCurrentQuestion
from quizzes.models import QuickQuiz
from quizzes.services import CalibrationService
from quizzes.stages import QuizStage

pytestmark = pytest.mark.django_db

POOL = make_questions()  # q1 … q10, two for each band; the right answer of every question is option 0


@pytest.fixture
def walking(make_quiz, queue):
    quiz = make_quiz(stage=QuizStage.AWAITING_CALIBRATION, calibration={"pool": POOL, "walk": []})
    open_ask = Authorization("a1", MeteredAction.QUIZ_CREATE, {}, False, CompletionPoints.of(MeteredAction.QUIZ_CREATE))
    run = GraphRun.objects.create(
        quick_quiz=quiz, graph="quick_quiz", trigger="start", status="paused",
        payload={"authorization": open_ask.to_payload()},
    )  # fmt: skip
    return CalibrationService(queue=queue, gate=CountingGate()), quiz, run


def walk_of(quiz):
    return QuickQuiz.objects.get(pk=quiz.pk).calibration["walk"]


class TestTheQuestion:
    def test_the_first_question_is_the_first_of_the_middle_band_and_shows_no_more_than_the_learner_needs(self, walking):
        service, quiz, _ = walking

        body = service.current(quiz)

        assert body["done"] is False and (body["step"], body["total"]) == (1, 5)
        assert body["question"] == {
            "id": "q5", "question": POOL[4]["question"], "options": POOL[4]["options"],
        }  # fmt: skip

    def test_nothing_about_the_band_or_the_answer_is_ever_shown(self, walking):
        service, quiz, _ = walking

        body = service.current(quiz)

        assert set(body) == {"done", "step", "total", "question"} and set(body["question"]) == {
            "id",
            "question",
            "options",
        }

    def test_a_quiz_that_is_not_waiting_has_no_question(self, make_quiz, queue):
        quiz = make_quiz(stage=QuizStage.READY)

        with pytest.raises(WrongStage):
            CalibrationService(queue=queue).current(quiz)


class TestAnswering:
    def test_a_right_answer_is_recorded_and_the_next_question_is_harder(self, walking):
        service, quiz, _ = walking

        body = service.answer(quiz, "q5", 0)

        assert walk_of(quiz) == [{"question_id": "q5", "band": "moderate", "correct": True}]
        assert body["step"] == 2 and body["question"]["id"] == "q7"  # the next band up

    def test_a_wrong_answer_and_an_i_dont_know_both_make_the_next_question_easier(self, walking):
        service, quiz, _ = walking
        assert service.answer(quiz, "q5", 3)["question"]["id"] == "q3"

        assert service.answer(quiz, "q3", None)["question"]["id"] == "q1"
        assert [s["correct"] for s in walk_of(quiz)] == [False, False]

    def test_a_boolean_is_not_an_answer(self, walking):
        service, quiz, _ = walking

        service.answer(quiz, "q5", True)

        assert walk_of(quiz)[0]["correct"] is False

    def test_an_answer_to_a_question_that_is_not_the_current_one_is_refused(self, walking):
        service, quiz, _ = walking

        with pytest.raises(NotTheCurrentQuestion):
            service.answer(quiz, "q9", 0)
        assert walk_of(quiz) == []

    def test_a_question_cannot_be_answered_twice(self, walking):
        service, quiz, _ = walking
        service.answer(quiz, "q5", 0)

        with pytest.raises(NotTheCurrentQuestion):
            service.answer(quiz, "q5", 3)
        assert len(walk_of(quiz)) == 1

    def test_a_quiz_that_is_not_waiting_takes_no_answers(self, make_quiz, queue):
        quiz = make_quiz(stage=QuizStage.READY)

        with pytest.raises(WrongStage):
            CalibrationService(queue=queue).answer(quiz, "q5", 0)


class TestTheEnd:
    def finish(self, service, quiz, answers):
        body = None
        for right in answers:
            quiz.refresh_from_db()  # a request reads the quiz afresh
            question = service.current(quiz)["question"]
            body = service.answer(quiz, question["id"], 0 if right else 3)
        return body

    def test_the_fifth_answer_gives_the_level_and_resumes_the_quiz_once(self, walking, queue):
        service, quiz, start = walking

        body = self.finish(service, quiz, [True] * 5)

        assert body == {"done": True, "level": "expert"}
        resumes = GraphRun.objects.filter(quick_quiz=quiz, trigger="resume_calibration")
        assert resumes.count() == 1 and queue.runs == [resumes.get()]
        assert resumes.get().payload["resume"] is True

    def test_the_open_authorization_is_carried_into_the_resume_run(self, walking):
        service, quiz, start = walking

        self.finish(service, quiz, [True] * 5)

        resume = GraphRun.objects.get(quick_quiz=quiz, trigger="resume_calibration")
        assert resume.payload["authorization"]["id"] == "a1"

    def test_a_sixth_answer_is_refused_and_no_second_run_appears(self, walking):
        service, quiz, _ = walking
        self.finish(service, quiz, [True] * 5)

        with pytest.raises(NoQuestionLeft):
            service.answer(quiz, "q1", 0)

        assert GraphRun.objects.filter(trigger="resume_calibration").count() == 1

    def test_asking_after_the_end_reports_the_level(self, walking):
        service, quiz, _ = walking
        self.finish(service, quiz, [False] * 5)
        quiz.refresh_from_db()

        assert service.current(quiz) == {"done": True, "level": "beginner"}

    @pytest.mark.parametrize(
        "answers", [[True, False, True, False, True], [False, True, True, True, False], [True] * 4 + [False]]
    )
    def test_the_level_is_the_ladders_table(self, walking, answers):
        service, quiz, _ = walking

        body = self.finish(service, quiz, answers)

        assert body["level"] == AdaptiveLadder().level(answers).value

    def test_the_questions_asked_are_all_different(self, walking):
        service, quiz, _ = walking
        self.finish(service, quiz, [True, False, True, False, True])

        asked = [s["question_id"] for s in walk_of(quiz)]
        assert len(set(asked)) == 5

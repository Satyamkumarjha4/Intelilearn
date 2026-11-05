"""Unit under test: `lessons.activity` (`ActivitySink`, `NullActivity`, `GuardedActivity`, `ActivitySinks`) and the
three places that report a sealed attempt: `AttemptService.submit` (a lesson's test), `QuizAttemptService.submit` (a
quick quiz) and `QuizService.submit` (a Quick check or Basics check handed in).

Why: a later feature gives a daily credit and a streak for real study. The services must say when study happened, and
only then, without learning what a credit is. Counting a submit that was refused, failed or empty would let a learner
farm the credit with requests that learn nothing, and a broken sink must never cost a learner their answers.

"Blank" is Phase 9's blank-attempt rule: an attempt with every answer blank is stored and scores 0
(`all_blank`). For a Quick check, whose answers are an option or "I don't know", it is every answer being
"I don't know".

Use cases:
- the default sink is the one `ACTIVITY_SINK` names, and that is `NullActivity`, which does nothing
- a sealed lesson test attempt is reported once, as a test attempt, with the learner and the instant it was sealed
- a sealed quick quiz attempt is reported once, as a quiz attempt; a Quick check and a Basics check handed in are
  reported once each, as a quick check
- an attempt that needs a judgement (written answers) is reported when it is sealed, not when it is marked
- an attempt of blank answers, a Quick check of only "I don't know", and an attempt a learner started but did not
  hand in are not reported
- a submit that fails (an invalid answer, a sealed attempt, a quiz out of stage, a refused gate) is not reported
- starting an attempt, saving an answer and retaking are not reported
- a sink that raises does not undo the submit: the attempt is sealed and the learner gets their result
"""

from datetime import UTC, datetime

import pytest
from support.activity import CountingActivity, RaisingActivity
from support.gates import RefusingGate
from support.lesson_data import make_blueprint_test, make_final_test, make_plan
from support.question_data import make_question
from support.quiz_data import make_prerequisites, make_questions

from lessons.activity import ActivityKind, ActivitySinks, GuardedActivity, NullActivity
from lessons.attempts import AttemptService
from lessons.errors import AttemptSealed, InvalidAnswers, QuizNotFound, WrongStage
from lessons.metering import ActionRefused
from lessons.models import Lesson, Quiz, QuizAttempt, Stage
from lessons.services import QuizService
from quizzes.attempts import QuizAttemptService
from quizzes.models import QuickQuizAttempt

pytestmark = pytest.mark.django_db

TEST = make_blueprint_test()
QUESTIONS = TEST["questions"]
BLANK = {"t1": None, "t2": "  ", "t4": []}


def ready_lesson(make_lesson):
    return make_lesson(stage=Stage.READY, final_test=TEST, plan=make_plan(), settings_snapshot={})


def right(question: dict):
    field = {"mcq": "correct_index", "msq": "correct_indices", "numerical": "answer"}[question["type"]]
    return question[field]


class TestTheDefaultSink:
    def test_the_default_is_the_one_the_setting_names_and_it_does_nothing(self, settings, user):
        assert settings.ACTIVITY_SINK == "lessons.activity.NullActivity"
        assert isinstance(ActivitySinks.configured(), NullActivity)

        NullActivity().record(user, ActivityKind.TEST_ATTEMPT, datetime.now(UTC))  # no error, nothing to see

    def test_a_setting_that_names_another_class_chooses_it(self, settings):
        settings.ACTIVITY_SINK = "support.activity.CountingActivity"

        assert isinstance(ActivitySinks.configured(), CountingActivity)

    def test_a_service_made_with_no_sink_uses_the_configured_one(self, settings, queue):
        settings.ACTIVITY_SINK = "support.activity.CountingActivity"

        service = AttemptService(queue=queue)

        assert isinstance(service.activity.sink, CountingActivity)


class TestGuardedActivity:
    def test_it_passes_a_record_on(self, user):
        sink = CountingActivity()

        GuardedActivity(sink).record(user, ActivityKind.QUIZ_ATTEMPT, datetime(2026, 1, 1, tzinfo=UTC))

        assert sink.kinds == ["quiz_attempt"]

    def test_it_keeps_a_failure_of_the_sink_to_itself(self, user, caplog):
        sink = RaisingActivity()

        GuardedActivity(sink).record(user, ActivityKind.QUIZ_ATTEMPT, datetime(2026, 1, 1, tzinfo=UTC))

        assert len(sink.recorded) == 1 and "activity" in caplog.text.lower()


class TestALessonTest:
    @pytest.fixture
    def sink(self):
        return CountingActivity()

    def started(self, make_lesson, queue, sink, **service):
        lesson = ready_lesson(make_lesson)
        svc = AttemptService(queue=queue, activity=sink, **service)
        return lesson, svc, svc.start(lesson).attempt

    def test_a_sealed_attempt_is_reported_once_with_the_learner_and_the_instant(self, make_lesson, queue, sink, user):
        lesson, service, attempt = self.started(make_lesson, queue, sink)
        assert sink.recorded == []  # starting is not study

        sealed, _ = service.submit(lesson, attempt.id, {q["id"]: right(q) for q in QUESTIONS})

        assert len(sink.recorded) == 1
        who, kind, at = sink.recorded[0]
        assert who == user and kind == ActivityKind.TEST_ATTEMPT and at == sealed.submitted_at

    def test_a_wrong_but_real_attempt_is_reported_too(self, make_lesson, queue, sink):
        lesson, service, attempt = self.started(make_lesson, queue, sink)

        service.submit(lesson, attempt.id, {"t1": 3})

        assert sink.kinds == ["test_attempt"]

    def test_an_attempt_of_blank_answers_is_not_reported(self, make_lesson, queue, sink):
        lesson, service, attempt = self.started(make_lesson, queue, sink)

        sealed, _ = service.submit(lesson, attempt.id, BLANK)

        assert sealed.all_blank is True and sink.recorded == []

    def test_an_attempt_with_nothing_sent_at_all_is_blank_and_not_reported(self, make_lesson, queue, sink):
        lesson, service, attempt = self.started(make_lesson, queue, sink)

        sealed, _ = service.submit(lesson, attempt.id)

        assert sealed.all_blank is True and sink.recorded == []

    def test_saving_answers_without_handing_in_is_not_reported(self, make_lesson, queue, sink):
        lesson, service, attempt = self.started(make_lesson, queue, sink)

        service.save_answer(lesson, attempt.id, "t1", right(QUESTIONS[0]))

        assert sink.recorded == []

    def test_a_submit_that_fails_is_not_reported(self, make_lesson, queue, sink):
        lesson, service, attempt = self.started(make_lesson, queue, sink)

        with pytest.raises(InvalidAnswers):
            service.submit(lesson, attempt.id, {"nope": 1})
        assert sink.recorded == []

        service.submit(lesson, attempt.id, {"t1": right(QUESTIONS[0])})
        with pytest.raises(AttemptSealed):
            service.submit(lesson, attempt.id, {"t1": right(QUESTIONS[0])})
        assert sink.kinds == ["test_attempt"]  # the second, refused submit added nothing

    def test_a_retake_that_is_refused_or_only_started_is_not_reported(self, make_lesson, queue, sink):
        lesson, service, attempt = self.started(make_lesson, queue, sink)
        service.submit(lesson, attempt.id, {"t1": right(QUESTIONS[0])})
        sink.recorded.clear()

        refused = AttemptService(queue=queue, activity=sink, gate=RefusingGate())
        with pytest.raises(ActionRefused):
            refused.start(lesson)
        service.start(lesson)  # a retake begins: questions are being made, nothing was handed in

        assert sink.recorded == []

    def test_an_attempt_with_written_answers_is_reported_when_sealed_not_when_marked(self, make_lesson, queue, sink):
        legacy = make_final_test()
        lesson = make_lesson(stage=Stage.READY, final_test=legacy, plan=None, settings_snapshot={})
        service = AttemptService(queue=queue, activity=sink)
        attempt = service.start(lesson).attempt
        ids = {q["type"]: q["id"] for q in legacy["questions"]}

        sealed, run = service.submit(lesson, attempt.id, {ids["mcq"]: 1, ids["short_answer"]: "Halve it."})

        assert run is not None and sealed.status == "grading"
        assert sink.kinds == ["test_attempt"]  # reported at the seal; the marking run adds nothing

    def test_a_broken_sink_does_not_undo_the_submit(self, make_lesson, queue):
        lesson = ready_lesson(make_lesson)
        broken = RaisingActivity()
        service = AttemptService(queue=queue, activity=broken)
        attempt = service.start(lesson).attempt

        sealed, _ = service.submit(lesson, attempt.id, {"t1": right(QUESTIONS[0])})

        assert len(broken.recorded) == 1
        sealed.refresh_from_db()
        assert sealed.status == "graded" and sealed.answers == {"t1": right(QUESTIONS[0])}


class TestAQuickQuiz:
    QUIZ_QUESTIONS = [make_question("mcq", 1, "easy"), make_question("msq", 2, "basic")]

    @pytest.fixture
    def sink(self):
        return CountingActivity()

    @pytest.fixture
    def taking(self, quiz, make_attempt):
        return quiz, make_attempt(quiz, status="in_progress", questions=self.QUIZ_QUESTIONS)

    def test_a_sealed_attempt_is_reported_once_as_a_quiz_attempt(self, taking, queue, sink, user):
        quiz, attempt = taking
        service = QuizAttemptService(queue=queue, activity=sink)

        sealed, _ = service.submit(quiz, attempt.id, {"t1": 1, "t2": [0, 2]})

        assert len(sink.recorded) == 1
        who, kind, at = sink.recorded[0]
        assert who == user and kind == ActivityKind.QUIZ_ATTEMPT and at == sealed.submitted_at

    def test_blank_answers_are_not_reported(self, taking, queue, sink):
        quiz, attempt = taking
        service = QuizAttemptService(queue=queue, activity=sink)

        sealed, _ = service.submit(quiz, attempt.id, {"t1": None, "t2": []})

        assert sealed.all_blank is True and sink.recorded == []

    def test_a_failed_submit_and_a_second_submit_are_not_reported(self, taking, queue, sink):
        quiz, attempt = taking
        service = QuizAttemptService(queue=queue, activity=sink)

        with pytest.raises(InvalidAnswers):
            service.submit(quiz, attempt.id, {"nope": 1})
        service.submit(quiz, attempt.id, {"t1": 1})
        with pytest.raises(AttemptSealed):
            service.submit(quiz, attempt.id, {"t1": 1})

        assert sink.kinds == ["quiz_attempt"]

    def test_an_attempt_still_being_made_cannot_be_handed_in_and_is_not_reported(self, quiz, make_attempt, queue, sink):
        attempt = make_attempt(quiz, status="generating", questions=[])
        service = QuizAttemptService(queue=queue, activity=sink)

        with pytest.raises(WrongStage):
            service.submit(quiz, attempt.id, {})

        assert sink.recorded == []

    def test_answering_one_question_is_not_reported(self, taking, queue, sink):
        quiz, attempt = taking

        QuizAttemptService(queue=queue, activity=sink).save_answer(quiz, attempt.id, "t1", 1)

        assert sink.recorded == []

    def test_a_broken_sink_does_not_undo_the_submit(self, taking, queue):
        quiz, attempt = taking

        sealed, _ = QuizAttemptService(queue=queue, activity=RaisingActivity()).submit(quiz, attempt.id, {"t1": 1})

        assert QuickQuizAttempt.objects.get(pk=attempt.pk).status == "graded" and sealed.status == "graded"


def make_checks(lesson, kind="diagnostic"):
    questions = make_questions() if kind == "diagnostic" else make_prerequisites()[1]
    quiz = Quiz.objects.create(lesson=lesson, kind=kind, questions=questions)
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage(f"awaiting_{kind}"), settings_snapshot={"prereq_trigger_max_correct": 2}
    )
    lesson.refresh_from_db()
    return quiz


def answers_for(quiz, right_count):
    return {
        q["id"]: q["correct_index"] if n < right_count else (q["correct_index"] + 1) % 4
        for n, q in enumerate(quiz.questions)
    }


class TestAQuickCheck:
    @pytest.fixture
    def sink(self):
        return CountingActivity()

    @pytest.mark.parametrize("kind", ["diagnostic", "prerequisite"])
    def test_a_quick_check_or_basics_check_handed_in_is_reported_once(self, lesson, queue, sink, user, kind):
        quiz = make_checks(lesson, kind)

        QuizService(queue=queue, activity=sink).submit(lesson, kind, answers_for(quiz, 5))

        assert len(sink.recorded) == 1
        who, reported, at = sink.recorded[0]
        assert who == user and reported == ActivityKind.QUICK_CHECK
        assert at == quiz.attempt.submitted_at

    def test_a_check_of_only_i_dont_know_is_blank_and_not_reported(self, lesson, queue, sink):
        quiz = make_checks(lesson)

        QuizService(queue=queue, activity=sink).submit(
            lesson, "diagnostic", {q["id"]: "dont_know" for q in quiz.questions}
        )

        assert sink.recorded == []

    def test_one_i_dont_know_among_real_answers_is_still_study(self, lesson, queue, sink):
        quiz = make_checks(lesson)
        answers = answers_for(quiz, 5) | {quiz.questions[0]["id"]: "dont_know"}

        QuizService(queue=queue, activity=sink).submit(lesson, "diagnostic", answers)

        assert sink.kinds == ["quick_check"]

    def test_a_submit_that_fails_is_not_reported(self, lesson, queue, sink):
        quiz = make_checks(lesson)
        service = QuizService(queue=queue, activity=sink)

        with pytest.raises(InvalidAnswers):
            service.submit(lesson, "diagnostic", {"q1": 1})  # not every question answered
        with pytest.raises(QuizNotFound):
            service.submit(lesson, "prerequisite", {})  # no Basics check was made for this lesson
        assert sink.recorded == []

        service.submit(lesson, "diagnostic", answers_for(quiz, 5))
        assert sink.kinds == ["quick_check"]

    def test_a_check_the_lesson_is_not_waiting_for_is_refused_and_not_reported(self, lesson, queue, sink):
        quiz = make_checks(lesson)
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)
        lesson.refresh_from_db()

        with pytest.raises(WrongStage):
            QuizService(queue=queue, activity=sink).submit(lesson, "diagnostic", answers_for(quiz, 5))

        assert sink.recorded == []

    def test_a_refused_gate_stores_nothing_and_reports_nothing(self, lesson, queue, sink):
        quiz = make_checks(lesson)
        service = QuizService(queue=queue, activity=sink, gate=RefusingGate())

        with pytest.raises(ActionRefused):
            service.submit(lesson, "diagnostic", answers_for(quiz, 5))

        assert sink.recorded == [] and not QuizAttempt.objects.filter(quiz=quiz).exists()

    def test_a_broken_sink_does_not_undo_the_submit(self, lesson, queue):
        quiz = make_checks(lesson)

        summary, run = QuizService(queue=queue, activity=RaisingActivity()).submit(
            lesson, "diagnostic", answers_for(quiz, 5)
        )

        assert run is not None and summary is not None
        assert QuizAttempt.objects.filter(quiz=quiz).exists()

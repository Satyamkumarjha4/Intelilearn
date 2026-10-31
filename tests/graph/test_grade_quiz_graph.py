"""Unit under test: the `grade_quiz` graph (`GradeAttemptGraphBuilder` with the `QuizAttemptStore`) and the two
`AttemptStore`s in `graph.attempt_stores`: a submitted quick quiz attempt is graded by the same graph as a legacy lesson
test.

Why: a quiz is the only place short and long answers are asked, so its attempts are the graph's main customer now. The
graph must find a quiz attempt through its quiz (not a lesson), save the finished card with a band from the quiz's own
thresholds, and offer nothing after it: a quiz has no follow-up. Everything else (asking the model only when there is
something to judge, asking again with the problems, failing with the reason) is the lesson graph's, unchanged.

Use cases:
- the quiz store loads the attempt's questions and answers, the quiz's snapshots and the learner's language, and names
  the quiz in the state so its model calls are logged against it
- open-ended answers of a quiz attempt are graded and the card saved on the attempt, with its band and marks, and no
  offer
- the band uses the quiz's thresholds from its settings snapshot
- an attempt with nothing to judge never calls the model; a grading that keeps failing ends the run and saves nothing
- only an attempt being graded is written: one that was failed or already graded is left alone
- the lesson store loads a test attempt through its lesson as before
- the registry has both graphs, and each is built with its own store
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from support.fixtures import budget_snapshot
from support.lesson_data import make_final_test

from graph.attempt_stores import LessonAttemptStore, QuizAttemptStore
from graph.builders import GradeAttemptGraphBuilder
from graph.errors import RunFailed
from graph.registry import GraphRegistry
from lessons.models import Lesson, Stage, TestSubmission
from quizzes.models import QuickQuiz, QuickQuizAttempt

pytestmark = pytest.mark.django_db(transaction=True)

FINAL_TEST = make_final_test()
IDS = {q["type"]: q["id"] for q in FINAL_TEST["questions"]}
SHORT, LONG = IDS["short_answer"], IDS["long_answer"]


@pytest.fixture
def attempt(quiz, flow_settings, make_attempt):
    QuickQuiz.objects.filter(pk=quiz.pk).update(config_snapshot=budget_snapshot(), settings_snapshot=flow_settings)
    answers = {IDS["mcq"]: 0, SHORT: "Halve it.", LONG: "Keep the invariant."}
    return make_attempt(quiz, answers=answers, questions=FINAL_TEST["questions"], status="grading")


def grading(*pairs):
    return {"grades": [{"question_id": q, "awards": awards, "feedback": f"About {q}."} for q, awards in pairs]}


def grade(attempt, ctx):
    graph = GradeAttemptGraphBuilder(QuizAttemptStore()).build(InMemorySaver())
    start = {"quiz_id": str(attempt.quiz_id), "attempt_id": str(attempt.id)}
    nodes = []
    for chunk in graph.stream(start, {"configurable": {"thread_id": "t"}}, context=ctx, stream_mode="updates"):
        nodes += list(chunk)
    return nodes


class TestTheQuizStore:
    def test_it_loads_the_attempt_through_its_quiz(self, attempt, quiz):
        loaded = QuizAttemptStore().load({"quiz_id": str(quiz.id), "attempt_id": str(attempt.id)})

        assert loaded.topic == quiz.topic and loaded.questions == FINAL_TEST["questions"]
        assert loaded.answers == attempt.answers and loaded.profile == {"preferred_language": "en"}
        assert loaded.snapshot == budget_snapshot() and loaded.state == {"quiz_id": str(quiz.id)}

    def test_another_quizs_attempt_is_not_found(self, attempt, make_quiz):
        other = make_quiz(topic="Other")

        with pytest.raises(QuickQuizAttempt.DoesNotExist):
            QuizAttemptStore().load({"quiz_id": str(other.id), "attempt_id": str(attempt.id)})


class TestGradingAQuizAttempt:
    def test_open_ended_answers_are_graded_and_the_card_saved_with_its_band(self, attempt, ctx, gateway):
        gateway.script("test.grade", grading((SHORT, [1, 0]), (LONG, [3, 1, 0])))

        nodes = grade(attempt, ctx)

        assert nodes == ["load_submission", "grade_open", "validate_grade", "persist_grade"]
        stored = QuickQuizAttempt.objects.get(pk=attempt.pk)
        assert stored.status == "graded" and stored.result["complete"] is True
        assert (stored.awarded, stored.available) == (
            stored.result["score"]["awarded"],
            stored.result["score"]["available"],
        )
        assert stored.band in ("fail", "normal", "excellent") and stored.graded_at is not None

    def test_the_model_calls_are_logged_against_the_quiz(self, attempt, ctx, gateway):
        gateway.script("test.grade", grading((SHORT, [1, 0]), (LONG, [3, 1, 0])))

        grade(attempt, ctx)

        assert {str(call.quiz_id) for call in gateway.called("test.grade")} == {str(attempt.quiz_id)}

    def test_no_offer_follows_a_quiz(self, attempt, ctx, gateway):
        gateway.script("test.grade", grading((SHORT, [1, 1]), (LONG, [4, 1, 1])))

        grade(attempt, ctx)

        assert not hasattr(QuickQuizAttempt.objects.get(pk=attempt.pk), "followup")

    @pytest.mark.parametrize(
        ("settings", "band"),
        [
            ({"band_fail_below": 99, "band_excellent_above": 100}, "fail"),
            ({"band_fail_below": 0, "band_excellent_above": 1}, "excellent"),
        ],
    )
    def test_the_band_uses_the_quizs_own_thresholds(self, attempt, quiz, ctx, gateway, settings, band):
        QuickQuiz.objects.filter(pk=quiz.pk).update(settings_snapshot={**quiz.settings_snapshot, **settings})
        gateway.script("test.grade", grading((SHORT, [1, 0]), (LONG, [3, 1, 0])))

        grade(attempt, ctx)

        assert QuickQuizAttempt.objects.get(pk=attempt.pk).band == band

    @pytest.mark.parametrize("answers", [{IDS["mcq"]: 1, IDS["numerical"]: "4"}, {SHORT: "  ", LONG: ""}])
    def test_nothing_to_judge_means_the_model_is_never_called(self, attempt, ctx, gateway, answers):
        QuickQuizAttempt.objects.filter(pk=attempt.pk).update(answers=answers)

        nodes = grade(attempt, ctx)

        assert nodes == ["load_submission", "persist_grade"] and gateway.called("test.grade") == []
        assert QuickQuizAttempt.objects.get(pk=attempt.pk).status == "graded"

    def test_a_grading_that_keeps_failing_ends_the_run_and_saves_nothing(self, attempt, ctx, gateway):
        gateway.script("test.grade", grading((SHORT, [9, 9])), grading((SHORT, [9, 9])))

        with pytest.raises(RunFailed, match="The grading still failed its checks"):
            grade(attempt, ctx)

        stored = QuickQuizAttempt.objects.get(pk=attempt.pk)
        assert stored.status == "grading" and stored.result is None

    @pytest.mark.parametrize("status", ["failed", "graded"])
    def test_an_attempt_that_is_not_being_graded_is_left_alone(self, attempt, ctx, gateway, status):
        QuickQuizAttempt.objects.filter(pk=attempt.pk).update(status=status, band="normal")
        gateway.script("test.grade", grading((SHORT, [1, 0]), (LONG, [3, 1, 0])))

        grade(attempt, ctx)

        stored = QuickQuizAttempt.objects.get(pk=attempt.pk)
        assert (stored.status, stored.band, stored.result) == (status, "normal", None)


class TestTheLessonStore:
    def test_it_loads_a_test_attempt_through_its_lesson(self, lesson, lesson_state):
        Lesson.objects.filter(pk=lesson.pk).update(
            stage=Stage.READY, config_snapshot=budget_snapshot(), settings_snapshot=lesson_state["settings"]
        )
        submission = TestSubmission.objects.create(lesson=lesson, answers={"a": 1}, questions=[{"id": "a"}])

        loaded = LessonAttemptStore().load({"lesson_id": str(lesson.id), "submission_id": str(submission.id)})

        assert (loaded.topic, loaded.questions, loaded.answers, loaded.state) == (
            lesson.topic,
            [{"id": "a"}],
            {"a": 1},
            {},
        )


class TestTheRegistry:
    def test_it_has_both_graphs_and_each_has_its_own_store(self):
        registry = GraphRegistry()

        assert registry.builder("grade_test").store.__class__ is LessonAttemptStore
        assert registry.builder("grade_quiz").store.__class__ is QuizAttemptStore
        assert registry.builder("quick_quiz") is not None

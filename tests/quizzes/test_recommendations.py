"""Unit under test: `quizzes.recommendations.QuizRecommendations`: what to do after a quiz attempt (plan §11.4, D18).

Why: a quiz about a topic should offer "Create a lesson for this"; a quiz made from lessons should say which of them to
study and what to look at, the lesson that lost most first. The advice is worked out in code from the score card, so it
costs nothing, never invents a lesson, and says so when a lesson has been deleted.

Use cases:
- nothing until the attempt is graded
- a topic quiz gets the concepts that lost marks, biggest loss first, and no lessons
- a quiz from lessons gets the lessons that lost marks, the most first, each with its concepts biggest loss first
- a lesson that lost nothing is not mentioned; a perfect attempt has no advice
- a lesson that was deleted since is still named but has no id to open
- ties are broken by the title, so the order is the same every time
"""

import pytest

from lessons.models import Lesson
from quizzes.models import QuickQuizSource
from quizzes.recommendations import QuizRecommendations

pytestmark = pytest.mark.django_db


def card(*rows):
    return {
        "complete": True, "score": {"awarded": 0, "available": 0, "percent": 0},
        "questions": [{"id": f"t{n}", "concept": c, "marks": m, "awarded": a} for n, (c, m, a) in enumerate(rows, 1)],
        "topics_to_revisit": [],
    }  # fmt: skip


def graded(quiz, make_attempt, sources, *rows):
    questions = [{"id": f"t{n}", "source": s} for n, s in enumerate(sources, 1)]
    return make_attempt(quiz, status="graded", questions=questions, result=card(*rows))


class TestForATopicQuiz:
    def test_the_concepts_that_lost_marks_come_from_the_card(self, quiz, make_attempt):
        attempt = make_attempt(
            quiz, status="graded", result=card(("A", 2, 0), ("B", 2, 1)) | {"topics_to_revisit": ["A", "B"]}
        )

        assert QuizRecommendations().of(quiz, attempt) == {"kind": "topic", "topics": ["A", "B"], "lessons": []}

    @pytest.mark.parametrize("status", ["in_progress", "grading", "failed", "generating"])
    def test_nothing_until_it_is_graded(self, quiz, make_attempt, status):
        assert QuizRecommendations().of(quiz, make_attempt(quiz, status=status)) is None


class TestForAQuizFromLessons:
    @pytest.fixture
    def mixed(self, make_quiz, make_ready_lesson):
        quiz = make_quiz(source_type="lessons", topic="Mixed")
        first, second = make_ready_lesson("First"), make_ready_lesson("Second")
        for lesson in (first, second):
            QuickQuizSource.objects.create(
                quiz=quiz, lesson=lesson, lesson_ref=lesson.pk, title=lesson.topic, level="foundation", share=3
            )
        return quiz, str(first.pk), str(second.pk)

    def test_the_lesson_that_lost_most_is_first_with_its_concepts_biggest_loss_first(self, mixed, make_attempt):
        quiz, a, b = mixed
        attempt = graded(
            quiz, make_attempt, [a, a, b, b], ("Loops", 2, 1), ("Recursion", 3, 0), ("Heaps", 2, 0), ("Trees", 2, 2)
        )

        advice = QuizRecommendations().of(quiz, attempt)

        assert advice["kind"] == "lessons" and advice["topics"] == []
        assert [(x["title"], x["marks_lost"], x["topics"]) for x in advice["lessons"]] == [
            ("First", 4, ["Recursion", "Loops"]), ("Second", 2, ["Heaps"]),
        ]  # fmt: skip
        assert advice["lessons"][0]["lesson_id"] == a and advice["lessons"][0]["level"] == "foundation"

    def test_a_lesson_that_lost_nothing_is_not_mentioned(self, mixed, make_attempt):
        quiz, a, b = mixed
        attempt = graded(quiz, make_attempt, [a, b], ("Loops", 2, 2), ("Heaps", 2, 1))

        assert [x["title"] for x in QuizRecommendations().of(quiz, attempt)["lessons"]] == ["Second"]

    def test_a_perfect_attempt_has_no_advice(self, mixed, make_attempt):
        quiz, a, b = mixed
        attempt = graded(quiz, make_attempt, [a, b], ("Loops", 2, 2), ("Heaps", 2, 2))

        assert QuizRecommendations().of(quiz, attempt)["lessons"] == []

    def test_a_deleted_lesson_is_still_named_but_cannot_be_opened(self, mixed, make_attempt):
        quiz, a, b = mixed
        attempt = graded(quiz, make_attempt, [a, b], ("Loops", 2, 0), ("Heaps", 2, 0))
        Lesson.objects.get(pk=a).delete()

        by_title = {x["title"]: x for x in QuizRecommendations().of(quiz, attempt)["lessons"]}

        assert by_title["First"]["lesson_id"] is None and by_title["Second"]["lesson_id"] == b

    def test_equal_losses_are_ordered_by_title(self, mixed, make_attempt):
        quiz, a, b = mixed
        attempt = graded(quiz, make_attempt, [b, a], ("Heaps", 2, 0), ("Loops", 2, 0))

        assert [x["title"] for x in QuizRecommendations().of(quiz, attempt)["lessons"]] == ["First", "Second"]

    def test_questions_without_a_lesson_are_left_out(self, mixed, make_attempt):
        quiz, a, _ = mixed
        attempt = graded(quiz, make_attempt, ["", a], ("Loops", 2, 0), ("Heaps", 2, 0))

        assert [x["title"] for x in QuizRecommendations().of(quiz, attempt)["lessons"]] == ["First"]

    def test_a_row_still_waiting_for_a_judge_counts_for_nothing(self, mixed, make_attempt):
        quiz, a, _ = mixed
        attempt = make_attempt(
            quiz, status="graded", questions=[{"id": "t1", "source": a}],
            result={"questions": [{"id": "t1", "concept": "X", "marks": 3, "awarded": None}], "topics_to_revisit": []},
        )  # fmt: skip

        assert QuizRecommendations().of(quiz, attempt)["lessons"] == []

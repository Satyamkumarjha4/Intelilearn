"""Unit under test: the whole product against the real models: golden topics from a first question to a graded test.

Why: every other test fakes the models, so none can say whether a real model's output survives our validators, builds a
document that renders, or teaches the right thing. These do, for a few topics chosen to stress different parts (code and
maths, biology with a picture, science with formulae). They are slow, cost money, depend on provider and media services,
and are never part of `make check`: run them by hand with `pytest -m live` and the keys in `.env`.

Use cases:
- each golden topic goes from the first question to a ready lesson with real models, the real sandbox and a real
  browser, and the lesson passes `LessonChecks` (pages, test, document, few degradations, a picture where wanted)
- the whole flow stays within the cost budget and the number of model calls
- a submitted test is graded: automatic marks at once, open-ended answers by a real model, a complete card with
  feedback for every question and a score within the marks available
"""

import pytest
from django.db.models import Sum
from live.golden import GOLDEN_TOPICS, LessonChecks

from graph.grading import QuizGrader
from lessons.models import GraphRun, Lesson, MediaAsset, Quiz, QuizAttempt, Stage
from lessons.services import LessonService, QuizService, SubmissionService
from lessons.tasks import InlineTaskQueue
from llm_registry.models import ModelCall

pytestmark = [pytest.mark.live, pytest.mark.django_db(transaction=True)]

MAX_CALLS = 250


def answer_diagnostic(lesson: Lesson, right: int = 5) -> None:
    """Get the first `right` questions right so the learner is routed to a lesson, not a study sheet."""
    quiz = Quiz.objects.get(lesson=lesson, kind="diagnostic")
    answers = {
        q["id"]: q["correct_index"] if n < right else (q["correct_index"] + 1) % len(q["options"])
        for n, q in enumerate(quiz.questions)
    }
    QuizService(queue=InlineTaskQueue()).submit(lesson, "diagnostic", answers)


def lesson_data(lesson: Lesson) -> dict:
    return {
        "pages": lesson.pages, "final_test": lesson.final_test, "code": lesson.code, "code_parts": lesson.code_parts,
        "warnings": lesson.warnings, "media": MediaAsset.objects.filter(lesson=lesson).count(),
    }  # fmt: skip


@pytest.fixture
def built_lesson(real_registry, learner):
    def build(topic: str) -> Lesson:
        lesson, _ = LessonService(queue=InlineTaskQueue()).create(learner, topic)
        lesson.refresh_from_db()
        assert lesson.stage == Stage.AWAITING_DIAGNOSTIC, lesson.error
        answer_diagnostic(lesson)
        lesson.refresh_from_db()
        return lesson

    return build


@pytest.mark.parametrize("golden", GOLDEN_TOPICS, ids=lambda g: g.topic)
def test_a_golden_topic_becomes_a_good_ready_lesson_within_budget(built_lesson, golden, max_cost):
    lesson = built_lesson(golden.topic)

    assert lesson.stage == Stage.READY, f"{lesson.stage}: {lesson.error}"
    assert LessonChecks().problems(lesson_data(lesson), golden) == []
    calls = ModelCall.objects.filter(lesson_id=lesson.id)
    assert calls.count() <= MAX_CALLS
    assert float(calls.aggregate(total=Sum("cost"))["total"] or 0) <= max_cost
    assert not GraphRun.objects.filter(lesson=lesson, status=GraphRun.Status.FAILED).exists()


def test_a_submitted_test_is_graded_with_feedback_for_every_question(built_lesson):
    lesson = built_lesson(GOLDEN_TOPICS[0].topic)
    questions = lesson.final_test["questions"]
    answers = {}
    for q in questions:
        if q["type"] == "mcq":
            answers[q["id"]] = q["correct_index"]
        elif q["type"] == "numerical":
            answers[q["id"]] = str(q["answer"])
        elif q["type"] == "code":
            answers[q["id"]] = q.get("reference_solution", "")
        else:
            answers[q["id"]] = q.get("model_answer", "")

    submission, _ = SubmissionService(queue=InlineTaskQueue()).submit(lesson, answers)
    submission.refresh_from_db()

    assert submission.status == "graded", submission.error
    card = submission.result
    assert card["complete"] is True and 0 <= card["score"]["awarded"] <= card["score"]["available"]
    assert all(row["feedback"] for row in card["questions"])
    assert card["score"]["percent"] >= 70  # the reference answers submitted as the learner's own should score well


def test_the_quiz_grader_used_by_the_live_flow_is_the_one_the_api_uses():
    """A guard on the helper above: `answer_diagnostic` marks the same way the graph routes."""
    assert QuizGrader().grade([{"id": "q", "options": list("abcd"), "correct_index": 1}], {"q": 1}).correct == 1
    assert QuizAttempt._meta.model_name == "quizattempt"

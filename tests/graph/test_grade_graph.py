"""Unit under test: the `grade_test` graph (`graph.builders.GradeTestGraphBuilder`): a submitted lesson test is graded.

Why: the nodes pass their own tests, but the wiring decides that the model is asked only when there is something to
judge, that a grading it got wrong is asked again with the problems, and that a run which cannot grade fails with its
reason instead of saving a half-finished score as final.

Use cases:
- open-ended answers are graded by the model and the finished card is saved on the submission
- a grading the validator refuses is asked again with the problems, then saved
- a grading that keeps failing ends the run with the reason, and nothing is saved as graded
- a submission with nothing to judge (only automatic questions, or blank answers) never calls the model
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from support.fixtures import budget_snapshot
from support.lesson_data import make_final_test

from graph.builders import GradeTestGraphBuilder
from graph.errors import RunFailed
from lessons.models import Lesson, Stage, TestSubmission

pytestmark = pytest.mark.django_db(transaction=True)

FINAL_TEST = make_final_test()
IDS = {q["type"]: q["id"] for q in FINAL_TEST["questions"]}
SHORT, CODE = IDS["short_answer"], IDS["code"]


@pytest.fixture
def submission(lesson, lesson_state):
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, final_test=FINAL_TEST, config_snapshot=budget_snapshot(),
        settings_snapshot=lesson_state["settings"],
    )  # fmt: skip
    answers = {IDS["mcq"]: 0, SHORT: "Halve it.", CODE: "def f(): pass"}
    return TestSubmission.objects.create(lesson=lesson, answers=answers)


def grading(*pairs):
    return {"grades": [{"question_id": q, "awarded": a, "feedback": f"About {q}."} for q, a in pairs]}


def grade(submission, ctx):
    graph = GradeTestGraphBuilder().build(InMemorySaver())
    start = {"lesson_id": str(submission.lesson_id), "submission_id": str(submission.id)}
    nodes = []
    for chunk in graph.stream(start, {"configurable": {"thread_id": "t"}}, context=ctx, stream_mode="updates"):
        nodes += list(chunk)
    return nodes


def test_open_ended_answers_are_graded_and_the_card_saved(submission, ctx, gateway):
    gateway.script("test.grade", grading((SHORT, 1), (CODE, 2)))

    nodes = grade(submission, ctx)

    assert nodes == ["load_submission", "grade_open", "validate_grade", "persist_grade"]
    stored = TestSubmission.objects.get(pk=submission.pk)
    assert stored.status == "graded" and stored.result["complete"] is True
    assert stored.result["score"]["awarded"] == 3 and stored.result["topics_to_revisit"] != []


def test_a_grading_the_validator_refuses_is_asked_again_with_the_problems(submission, ctx, gateway):
    gateway.script("test.grade", grading((SHORT, 9), (CODE, 2)), grading((SHORT, 2), (CODE, 2)))

    nodes = grade(submission, ctx)

    assert nodes.count("grade_open") == 2 and nodes[-1] == "persist_grade"
    assert "awarded 9 but the question is worth 2" in gateway.called("test.grade")[1].messages[1].content
    assert TestSubmission.objects.get(pk=submission.pk).result["score"]["awarded"] == 4


def test_a_grading_that_keeps_failing_ends_the_run_with_the_reason(submission, ctx, gateway):
    gateway.script("test.grade", grading((SHORT, 9)), grading((SHORT, 9)))

    with pytest.raises(RunFailed, match="The grading still failed its checks after 2 attempts"):
        grade(submission, ctx)

    assert TestSubmission.objects.get(pk=submission.pk).status == "grading"  # the runner marks it failed


@pytest.mark.parametrize("answers", [{IDS["mcq"]: 1, IDS["numerical"]: "4"}, {SHORT: "  ", CODE: ""}])
def test_nothing_to_judge_means_the_model_is_never_called(submission, ctx, gateway, answers):
    TestSubmission.objects.filter(pk=submission.pk).update(answers=answers)

    nodes = grade(submission, ctx)

    assert nodes == ["load_submission", "persist_grade"] and gateway.called("test.grade") == []
    assert TestSubmission.objects.get(pk=submission.pk).status == "graded"

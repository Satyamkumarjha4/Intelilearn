"""Unit under test: the `grade_test` graph (`graph.builders.GradeAttemptGraphBuilder`): a submitted lesson test is
graded.

Why: the nodes pass their own tests, but the wiring decides that the model is asked only when there is something to
judge, that a grading it got wrong is asked again with the problems, and that a run which cannot grade fails with its
reason instead of saving a half-finished score as final.

Use cases:
- open-ended answers are graded by the model, one whole award per criterion, and the finished card is saved on the
  submission
- a grading the validator refuses is asked again with the problems, then saved
- a grading that keeps failing ends the run with the reason, and nothing is saved as graded
- a submission with nothing to judge (only automatic questions, or blank answers) never calls the model
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from support.fixtures import budget_snapshot
from support.lesson_data import make_final_test

from graph.builders import GradeAttemptGraphBuilder
from graph.errors import RunFailed
from lessons.models import Lesson, Stage, TestSubmission

pytestmark = pytest.mark.django_db(transaction=True)

FINAL_TEST = make_final_test()
IDS = {q["type"]: q["id"] for q in FINAL_TEST["questions"]}
SHORT, LONG = IDS["short_answer"], IDS["long_answer"]  # 3 marks in two criteria (1 + 2), 6 marks in three (4 + 1 + 1)


@pytest.fixture
def submission(lesson, lesson_state):
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, config_snapshot=budget_snapshot(),
        settings_snapshot=lesson_state["settings"],
    )  # fmt: skip
    answers = {IDS["mcq"]: 0, SHORT: "Halve it.", LONG: "Keep the invariant."}
    return TestSubmission.objects.create(
        lesson=lesson, answers=answers, questions=FINAL_TEST["questions"], status=TestSubmission.Status.GRADING
    )


def grading(*pairs):
    return {"grades": [{"question_id": q, "awards": awards, "feedback": f"About {q}."} for q, awards in pairs]}


def grade(submission, ctx):
    graph = GradeAttemptGraphBuilder().build(InMemorySaver())
    start = {"lesson_id": str(submission.lesson_id), "submission_id": str(submission.id)}
    nodes = []
    for chunk in graph.stream(start, {"configurable": {"thread_id": "t"}}, context=ctx, stream_mode="updates"):
        nodes += list(chunk)
    return nodes


def test_open_ended_answers_are_graded_and_the_card_saved(submission, ctx, gateway):
    gateway.script("test.grade", grading((SHORT, [1, 0]), (LONG, [3, 1, 0])))

    nodes = grade(submission, ctx)

    assert nodes == ["load_submission", "grade_open", "validate_grade", "persist_grade"]
    stored = TestSubmission.objects.get(pk=submission.pk)
    assert stored.status == "graded" and stored.result["complete"] is True
    assert stored.result["score"]["awarded"] == 5 and stored.result["topics_to_revisit"] != []


def test_a_grading_the_validator_refuses_is_asked_again_with_the_problems(submission, ctx, gateway):
    gateway.script(
        "test.grade", grading((SHORT, [1, 9]), (LONG, [4, 1, 1])), grading((SHORT, [1, 2]), (LONG, [4, 1, 1]))
    )

    nodes = grade(submission, ctx)

    assert nodes.count("grade_open") == 2 and nodes[-1] == "persist_grade"
    assert "award 2 is 9 but that criterion is worth 2" in gateway.called("test.grade")[1].messages[1].content
    assert TestSubmission.objects.get(pk=submission.pk).result["score"]["awarded"] == 9


def test_a_grading_that_keeps_failing_ends_the_run_with_the_reason(submission, ctx, gateway):
    gateway.script("test.grade", grading((SHORT, [9, 9])), grading((SHORT, [9, 9])))

    with pytest.raises(RunFailed, match="The grading still failed its checks after 2 attempts"):
        grade(submission, ctx)

    assert TestSubmission.objects.get(pk=submission.pk).status == "grading"  # the runner marks it failed


@pytest.mark.parametrize("answers", [{IDS["mcq"]: 1, IDS["numerical"]: "4"}, {SHORT: "  ", LONG: ""}])
def test_nothing_to_judge_means_the_model_is_never_called(submission, ctx, gateway, answers):
    TestSubmission.objects.filter(pk=submission.pk).update(answers=answers)

    nodes = grade(submission, ctx)

    assert nodes == ["load_submission", "persist_grade"] and gateway.called("test.grade") == []
    assert TestSubmission.objects.get(pk=submission.pk).status == "graded"

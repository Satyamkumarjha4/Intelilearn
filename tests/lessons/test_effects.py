"""Unit under test: `lessons.effects.RunEffects` and `SubmissionEffect`: what a run that did not finish leaves behind
besides its own row.

Why: a test submission that stays "grading" for ever leaves the learner staring at a spinner and, because one grading
at a time is allowed, unable to submit again. Every way a grading run can stop must release it.

Use cases:
- a grading run that stopped marks its submission failed with the reason
- a submission that was already graded is left alone
- a run of any other graph has no effect, and a run without a submission id is harmless
- effects can be replaced, so a new graph adds its own without editing this class
"""

import pytest

from lessons.effects import RunEffects, SubmissionEffect
from lessons.models import GraphRun, Lesson, TestSubmission

pytestmark = pytest.mark.django_db


def grading_run(lesson, submission=None, graph=GraphRun.Graph.GRADE_TEST):
    payload = {"input": {"submission_id": str(submission.id)}} if submission else {}
    return GraphRun.objects.create(lesson=lesson, graph=graph, trigger=GraphRun.Trigger.GRADE, payload=payload)


def test_a_grading_run_that_stopped_marks_its_submission_failed_with_the_reason(lesson):
    submission = TestSubmission.objects.create(lesson=lesson)

    RunEffects().on_stopped(grading_run(lesson, submission), "Every AI model failed.")

    submission.refresh_from_db()
    assert (submission.status, submission.error) == ("failed", "Every AI model failed.")


def test_a_submission_that_was_already_graded_is_left_alone(lesson):
    submission = TestSubmission.objects.create(lesson=lesson, status=TestSubmission.Status.GRADED, result={"x": 1})

    RunEffects().on_stopped(grading_run(lesson, submission), "late failure")

    submission.refresh_from_db()
    assert submission.status == "graded" and submission.error == ""


def test_other_graphs_and_runs_without_a_submission_have_no_effect(lesson):
    submission = TestSubmission.objects.create(lesson=lesson)

    RunEffects().on_stopped(grading_run(lesson, submission, graph=GraphRun.Graph.RUNTIME_REPAIR), "x")
    RunEffects().on_stopped(grading_run(lesson), "x")

    submission.refresh_from_db()
    assert submission.status == "grading" and Lesson.objects.get(pk=lesson.pk).stage == lesson.stage


def test_effects_can_be_replaced(lesson):
    seen = []

    class Recorder:
        def apply(self, run, message):
            seen.append((run.graph, message))

    effects = RunEffects({GraphRun.Graph.RUNTIME_REPAIR: Recorder()})

    effects.on_stopped(grading_run(lesson, graph=GraphRun.Graph.RUNTIME_REPAIR), "boom")
    effects.on_stopped(grading_run(lesson), "ignored")

    assert seen == [("runtime_repair", "boom")]
    assert isinstance(RunEffects().effects[GraphRun.Graph.GRADE_TEST], SubmissionEffect)

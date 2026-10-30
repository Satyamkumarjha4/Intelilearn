"""Unit under test: `lessons.effects.RunEffects` and `SubmissionEffect`: what a run that did not finish leaves behind
besides its own row.

Why: a test submission that stays "grading" for ever leaves the learner staring at a spinner and, because the test
can be submitted only once, unable to ask for the grading to be run again. Every way a grading run can stop must
release it.

Use cases:
- a grading run that stopped marks its submission failed with the reason
- a submission that was already graded is left alone
- a run of any other graph has no effect, and a run without a submission id is harmless
- effects can be replaced, so a new graph adds its own without editing this class
"""

import pytest

from lessons.effects import AttemptGenerationEffect, RunEffects, SubmissionEffect
from lessons.models import GraphRun, Lesson, TestSubmission

pytestmark = pytest.mark.django_db


def grading_run(lesson, submission=None, graph=GraphRun.Graph.GRADE_TEST):
    payload = {"input": {"submission_id": str(submission.id)}} if submission else {}
    return GraphRun.objects.create(lesson=lesson, graph=graph, trigger=GraphRun.Trigger.GRADE, payload=payload)


def test_a_grading_run_that_stopped_marks_its_submission_failed_with_the_reason(lesson):
    submission = TestSubmission.objects.create(lesson=lesson, status=TestSubmission.Status.GRADING)

    RunEffects().on_stopped(grading_run(lesson, submission), "Every AI model failed.")

    submission.refresh_from_db()
    assert (submission.status, submission.error) == ("failed", "Every AI model failed.")


def test_a_submission_that_was_already_graded_is_left_alone(lesson):
    submission = TestSubmission.objects.create(lesson=lesson, status=TestSubmission.Status.GRADED, result={"x": 1})

    RunEffects().on_stopped(grading_run(lesson, submission), "late failure")

    submission.refresh_from_db()
    assert submission.status == "graded" and submission.error == ""


def test_other_graphs_and_runs_without_a_submission_have_no_effect(lesson):
    submission = TestSubmission.objects.create(lesson=lesson, status=TestSubmission.Status.GRADING)

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


class TestAttemptGenerationEffect:
    def retake(self, lesson, status="generating"):
        TestSubmission.objects.create(lesson=lesson, attempt_no=1, status="graded")
        attempt = TestSubmission.objects.create(lesson=lesson, attempt_no=2, status=status)
        run = GraphRun.objects.create(
            lesson=lesson, graph=GraphRun.Graph.QUESTION_BANK, trigger=GraphRun.Trigger.RETAKE,
            payload={"input": {"attempt_id": str(attempt.id)}},
        )  # fmt: skip
        return attempt, run

    def test_a_retake_that_failed_or_was_stopped_leaves_no_attempt_and_no_gap_in_the_numbers(self, lesson):
        attempt, run = self.retake(lesson)

        RunEffects().on_stopped(run, "Every AI model failed.")

        assert not TestSubmission.objects.filter(pk=attempt.pk).exists()
        assert list(lesson.submissions.values_list("attempt_no", flat=True)) == [1]

    @pytest.mark.parametrize("status", ["in_progress", "graded"])
    def test_an_attempt_that_already_has_its_questions_is_left_alone(self, lesson, status):
        attempt, run = self.retake(lesson, status=status)

        RunEffects().on_stopped(run, "late failure")

        assert TestSubmission.objects.filter(pk=attempt.pk, status=status).exists()

    def test_the_effect_is_registered_for_the_question_bank_graph_and_the_grading_graph_still_has_its_own(self):
        effects = RunEffects().effects

        assert isinstance(effects[GraphRun.Graph.QUESTION_BANK], AttemptGenerationEffect)
        assert isinstance(effects[GraphRun.Graph.GRADE_TEST], SubmissionEffect)

    def test_the_run_of_a_retake_that_has_no_attempt_id_has_no_effect(self, lesson):
        TestSubmission.objects.create(lesson=lesson, attempt_no=1, status="graded")
        run = GraphRun.objects.create(lesson=lesson, graph=GraphRun.Graph.QUESTION_BANK, trigger="retake")

        RunEffects().on_stopped(run, "x")

        assert TestSubmission.objects.filter(lesson=lesson).count() == 1

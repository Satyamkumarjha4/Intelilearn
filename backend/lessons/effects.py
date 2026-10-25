"""What else a run that did not finish leaves behind besides its own row.

A lesson's main flow fails the lesson (`Lesson.fail`, which leaves a ready lesson alone); a submitted test that was
being graded must not stay "grading" for ever, so its submission is marked failed and the learner can submit again.
"""

from typing import Protocol

from .models import GraphRun, TestSubmission


class RunEffect(Protocol):
    def apply(self, run: GraphRun, message: str) -> None: ...


class SubmissionEffect:
    """The `grade_test` run for a submission ended without grading it."""

    def apply(self, run: GraphRun, message: str) -> None:
        submission_id = (run.payload.get("input") or {}).get("submission_id")
        TestSubmission.objects.filter(pk=submission_id, status=TestSubmission.Status.GRADING).update(
            status=TestSubmission.Status.FAILED, error=message
        )


class RunEffects:
    """The effect of a run that failed or was cancelled, by the graph it ran."""

    def __init__(self, effects: dict[str, RunEffect] | None = None):
        self.effects = effects if effects is not None else {GraphRun.Graph.GRADE_TEST: SubmissionEffect()}

    def on_stopped(self, run: GraphRun, message: str) -> None:
        if effect := self.effects.get(run.graph):
            effect.apply(run, message)

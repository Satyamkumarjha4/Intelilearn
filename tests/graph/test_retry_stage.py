"""Unit under test: what a lesson that Retry left `failed` does when its thread carries on (`Node.__call__`'s move from
`failed` to the stage of the node that runs, and `StopPoint`, which decides whether Retry restores any stage at all).

Why: Stop is noticed after the node that is running finishes, so by the time anyone reads the lesson's stage the thread
can be a step ahead of it. Retry used to put back the stage read at the click; the thread had left that stage, and the
build then failed at its last step ("awaiting_diagnostic to ready"). Two builds hit this, one in 9.3 (a self-rated
lesson stopped before its first step finished) and one in 9.4 (a Stop just after a quiz was answered). The cause is
one: a stage read while the thread is moving cannot be trusted. Now Retry restores a stage only when the thread is at a
question (known to the click for a run nobody started, and to the worker that notices the Stop for one it had), and
otherwise the lesson stays `failed` until the first node that declares a stage runs and moves it. These tests walk the
compiled graph from that state to the end.

Use cases:
- a self-rated lesson left failed before its first step finished is carried through to ready by the nodes that run
- a quick check answered, then stopped and retried with the lesson left failed, is carried through to ready
- a lesson that has no stop at all is unchanged by this (the ordinary run still reaches ready)
"""

import pytest
from support.driver import GraphDriver
from support.study_data import CONCEPTS, make_cheat_sheet, make_revision_sheet

from lessons.models import Lesson, Stage, StudyMaterial

pytestmark = pytest.mark.django_db(transaction=True)

BOTH = ["cheat_sheet", "revision_sheet"]
ASSESSMENT = {
    "level": "foundation", "known_concepts": [], "gaps": [], "prerequisites_to_cover": [], "start_point": "Halving",
    "author_notes": "Brisk.", "confidence": "medium",
}  # fmt: skip


def by_kind(messages):
    return make_cheat_sheet() if "CHEAT SHEET" in messages[0].content else make_revision_sheet()


@pytest.fixture
def run(lesson, ctx, lesson_state):
    return GraphDriver(lesson, ctx, lesson_state)


def test_a_self_rated_lesson_left_failed_before_its_first_step_is_carried_to_ready(run, gateway, lesson):
    Lesson.objects.filter(pk=lesson.pk).update(
        entry="self_rating", self_rating_halves=5, intent="sheets", stage=Stage.FAILED, error="Cancelled."
    )
    gateway.respond("study.generate", by_kind)

    run.start(sheet_kinds=BOTH)

    stored = Lesson.objects.get(pk=lesson.pk)
    assert (stored.stage, stored.error) == (Stage.READY, "") and StudyMaterial.objects.count() == 2


def test_a_quick_check_answered_and_then_stopped_is_carried_to_ready_by_the_node_that_runs(
    run, gateway, valid_bundle, lesson
):
    Lesson.objects.filter(pk=lesson.pk).update(intent="sheets")
    questions = [{**q, "concept": CONCEPTS[n % 2] + f" {n}"} for n, q in enumerate(valid_bundle["diagnostic"])]
    gateway.script("diagnostic.generate", {**valid_bundle, "diagnostic": questions})
    gateway.script("learner.assess", ASSESSMENT)
    gateway.respond("study.generate", by_kind)
    run.start(sheet_kinds=BOTH)
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_DIAGNOSTIC
    # The learner answered; the Stop landed while the worker graded it; Retry restored nothing.
    Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED, error="Cancelled.")

    run.answer("diagnostic", right=7)

    stored = Lesson.objects.get(pk=lesson.pk)
    assert (stored.stage, stored.error) == (Stage.READY, "") and StudyMaterial.objects.count() == 2


def test_an_ordinary_run_still_reaches_ready(run, gateway, lesson):
    Lesson.objects.filter(pk=lesson.pk).update(entry="self_rating", self_rating_halves=10, intent="sheets")
    gateway.respond("study.generate", by_kind)

    run.start(sheet_kinds=BOTH)

    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY

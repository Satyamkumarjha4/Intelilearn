"""Unit under test: the mastery nodes in `graph.nodes.mastery`: offering the choice to a learner who aced the quick
check, taking their pick, and the failure node of the extra-sheet graph.

Why: a learner who aced the diagnostic gets only this. A node that forgets the stage change leaves the browser on the
wrong screen, and one that lets a stale pick through (a sheet kind from the old three-sheet choice, which no lesson
waits at any more) would send the flow down a path that no longer exists.

Use cases:
- publish_mastery_options moves the lesson to awaiting_choice and has no other effect
- await_choice accepts the two choices (as a body or bare), refuses the sheet kinds of the old three-sheet choice and
  anything else, and waits with its own kind of interrupt
- the single-sheet nodes of that old choice no longer exist
- the extra-sheet failure node raises a readable error so the run fails without failing the lesson
"""

import pytest

from graph.errors import RunFailed
from graph.nodes.mastery import AwaitChoiceNode, FailStudyMaterialNode, PublishMasteryOptionsNode
from lessons.models import Lesson, Stage


def test_publishing_the_options_moves_the_lesson_to_awaiting_choice(lesson, lesson_state, runtime):
    Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC)

    update = PublishMasteryOptionsNode()(lesson_state, runtime)

    assert update == {}
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_CHOICE


class TestAwaitChoice:
    @pytest.mark.parametrize("choice", ["lesson", "sheets"])
    def test_accepts_the_two_choices_as_a_body_or_bare(self, choice):
        assert AwaitChoiceNode().accept({"choice": choice}) == choice
        assert AwaitChoiceNode().accept(choice) == choice

    @pytest.mark.parametrize("kind", ["cheat_sheet", "revision_sheet", "practice_sheet"])
    def test_a_sheet_kind_from_the_old_three_sheet_choice_is_refused(self, kind):
        """No lesson waits at that choice any more (phase 9.8), so nothing can send one."""
        for value in (kind, {"choice": kind}):
            with pytest.raises(ValueError, match="Unknown choice"):
                AwaitChoiceNode().accept(value)

    @pytest.mark.parametrize("value", ["poster", "", None, 3, ["cheat_sheet"], {}, {"choice": "poster"}, {"kind": "x"}])
    def test_refuses_anything_else(self, value):
        with pytest.raises(ValueError, match="Unknown choice"):
            AwaitChoiceNode().accept(value)

    def test_waits_with_its_own_kind_of_interrupt(self):
        assert (AwaitChoiceNode.kind, AwaitChoiceNode.result_key) == ("mastery_choice", "mastery_choice")


def test_the_extra_sheet_failure_node_raises_the_graphs_reason(lesson_state, runtime):
    with pytest.raises(RunFailed, match="The cheat sheet still failed its checks"):
        FailStudyMaterialNode()(lesson_state | {"error": "The cheat sheet still failed its checks"}, runtime)


def test_the_extra_sheet_failure_node_has_a_default_reason(lesson_state, runtime):
    with pytest.raises(RunFailed, match="could not be written"):
        FailStudyMaterialNode()(lesson_state, runtime)


@pytest.mark.parametrize("name", ["GenerateStudyMaterialNode", "ValidateStudyMaterialNode", "PersistStudyMaterialNode"])
def test_the_single_sheet_nodes_of_the_old_choice_are_gone(name):
    from graph.nodes import mastery

    assert not hasattr(mastery, name)

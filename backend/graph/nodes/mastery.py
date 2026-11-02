"""The mastery path: the learner aced the diagnostic, so offer the Expert lesson or two study sheets.

    publish_mastery_options → await_choice → (the Expert lesson's assessment | the sheets segment)

The sheets themselves are written by the sheets segment (`graph/nodes/sheets.py`). This module keeps the choice, the
concepts a sheet rests on, and the failure node of the small `study_material` graph that adds sheets to a ready lesson.
"""

from typing import Any

from lessons.models import Quiz, Stage

from ..context import FlowContext
from ..errors import RunFailed
from .base import AwaitNode, Node, PublishNode


class PublishMasteryOptionsNode(PublishNode):
    name = "publish_mastery_options"

    def publish(self, state: dict, ctx: FlowContext) -> dict:
        self.lesson(state).advance_to(Stage.AWAITING_CHOICE)
        return {}


class AwaitChoiceNode(AwaitNode):
    name = "await_choice"
    kind = "mastery_choice"
    result_key = "mastery_choice"

    #: what a learner who aced the quiz can choose
    CHOICES = ("lesson", "sheets")

    def accept(self, value: Any) -> str:
        """`{"choice": "lesson" | "sheets"}` (a bare `"lesson"` or `"sheets"` is taken too) → the choice."""
        choice = value.get("choice") if isinstance(value, dict) else value
        if choice not in self.CHOICES:
            raise ValueError(f"Unknown choice {choice!r}")
        return choice


class DiagnosticConcepts:
    """What a sheet must cover: the diagnostic's concepts."""

    @staticmethod
    def of(state: dict) -> list[str]:
        """From the state, or (an extra sheet, a branch of the two-sheet fan-out) from the stored quiz."""
        if bundle := state.get("bundle"):
            return [q["concept"] for q in bundle["diagnostic"]]
        quiz = Quiz.objects.filter(lesson_id=state["lesson_id"], kind=Quiz.Kind.DIAGNOSTIC).first()
        return [q["concept"] for q in quiz.questions] if quiz else []


class FailStudyMaterialNode(Node):
    """The extra-sheet graph has no Retry: it ends the run with the reason, and the lesson stays as it was."""

    name = "fail_study_material"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        raise RunFailed(state.get("error") or "The study sheet could not be written.")

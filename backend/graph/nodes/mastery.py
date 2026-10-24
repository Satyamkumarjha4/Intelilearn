"""The mastery path: the learner aced the diagnostic, so offer a study sheet instead of a lesson.

    publish_mastery_options → await_choice → generate_study_material → validate_study_material → persist_study_material

The same generate, validate and persist nodes also form the small `study_material` graph, which writes another sheet
type later (`state["extra_material"]` is then true and the lesson stays `ready`).
"""

from typing import Any

from pydantic import BaseModel

from lessons.models import MaterialKind, Quiz, Stage, StudyMaterial

from ..context import FlowContext
from ..errors import RunFailed
from ..prompts import StudyMaterialPrompt
from ..schemas import MATERIAL_SCHEMAS
from ..validators import StudyMaterialValidator, Validator
from .base import AwaitNode, LLMNode, Node, PublishNode, ValidateNode


class PublishMasteryOptionsNode(PublishNode):
    name = "publish_mastery_options"

    def publish(self, state: dict, ctx: FlowContext) -> dict:
        self.lesson(state).advance_to(Stage.AWAITING_CHOICE)
        return {}


class AwaitChoiceNode(AwaitNode):
    name = "await_choice"
    kind = "mastery_choice"
    result_key = "mastery_choice"

    def accept(self, value: Any) -> str:
        if value not in MaterialKind.values:
            raise ValueError(f"Unknown study sheet {value!r}")
        return value


def diagnostic_concepts(state: dict) -> list[str]:
    """What the sheet must cover: the diagnostic's concepts, from the state or (an extra sheet) the stored quiz."""
    if bundle := state.get("bundle"):
        return [q["concept"] for q in bundle["diagnostic"]]
    quiz = Quiz.objects.filter(lesson_id=state["lesson_id"], kind=Quiz.Kind.DIAGNOSTIC).first()
    return [q["concept"] for q in quiz.questions] if quiz else []


class GenerateStudyMaterialNode(LLMNode):
    name = "generate_study_material"
    stage = Stage.GENERATING_MATERIAL
    node_key = "study.generate"
    prompt = StudyMaterialPrompt()
    feedback_key = "material"

    def schema_of(self, state: dict) -> type[BaseModel]:
        return MATERIAL_SCHEMAS[state["mastery_choice"]]

    def before(self, state: dict) -> None:
        if not state.get("extra_material"):
            self.lesson(state).advance_to(Stage.GENERATING_MATERIAL)

    def subject(self, state: dict) -> dict:
        return state | {"kind": state["mastery_choice"], "concepts": diagnostic_concepts(state)}

    def to_state(self, output: BaseModel, state: dict, ctx: FlowContext) -> dict:
        return {"study_material": output.model_dump(mode="json"), "attempts": {"material": 1}}


class ValidateStudyMaterialNode(ValidateNode):
    name = "validate_study_material"
    stage = Stage.GENERATING_MATERIAL
    node_key = "study.generate"
    feedback_key = "material"
    retry_node = "generate_study_material"
    label = "The study sheet"

    def validator(self, state: dict, ctx: FlowContext) -> Validator:
        return StudyMaterialValidator(ctx.sandbox)

    def subject(self, state: dict) -> dict:
        return state["study_material"]

    def context(self, state: dict) -> dict:
        return {"kind": state["mastery_choice"], "concepts": diagnostic_concepts(state)}

    def label_of(self, state: dict) -> str:
        return f"The {MaterialKind(state['mastery_choice']).label.lower()}"


class PersistStudyMaterialNode(Node):
    name = "persist_study_material"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        StudyMaterial.objects.update_or_create(
            lesson_id=state["lesson_id"], kind=state["mastery_choice"], defaults={"content": state["study_material"]}
        )
        self.lesson(state).advance_to(Stage.READY)
        return {}


class FailStudyMaterialNode(Node):
    """The extra-sheet graph has no Retry: it ends the run with the reason, and the lesson stays as it was."""

    name = "fail_study_material"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        raise RunFailed(state.get("error") or "The study sheet could not be written.")

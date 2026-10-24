"""Mastery path: the learner aced the diagnostic, so offer a study sheet instead of a lesson.

The same generate → validate → persist nodes also form the small `study_material` graph, which writes another
sheet type later (state["extra_material"] is then true and the lesson stays `ready`).
"""

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from lessons.models import MaterialKind, Quiz, Stage, StudyMaterial

from .. import prompts, validators
from ..context import FlowContext, emit, llm
from ..schemas import MATERIAL_SCHEMAS
from .common import outcome, route_check, set_stage


def publish_mastery_options(state, runtime: Runtime[FlowContext]):
    set_stage(state["lesson_id"], Stage.AWAITING_CHOICE)
    emit({"type": "awaiting_input", "kind": "mastery_choice"})
    return {}


def await_choice(state):
    choice = interrupt({"kind": "mastery_choice"})
    if choice not in MaterialKind.values:
        raise ValueError(f"Unknown study material kind {choice!r}")
    return {"mastery_choice": choice}


def _concepts(state) -> list[str]:
    if bundle := state.get("bundle"):
        return [q["concept"] for q in bundle["diagnostic"]]
    quiz = Quiz.objects.filter(lesson_id=state["lesson_id"], kind=Quiz.Kind.DIAGNOSTIC).first()
    return [q["concept"] for q in quiz.questions] if quiz else []


def generate_study_material(state, runtime: Runtime[FlowContext]):
    kind = state["mastery_choice"]
    if not state.get("extra_material"):
        set_stage(state["lesson_id"], Stage.GENERATING_MATERIAL)
    feedback = (state.get("feedback") or {}).get("material")
    messages = prompts.study_material({**state, "concepts": _concepts(state)}, kind, feedback)
    result = llm(runtime, state, "study.generate", messages, schema=MATERIAL_SCHEMAS[kind])
    return {"study_material": result.output.model_dump(mode="json"), "attempts": {"material": 1}}


def validate_study_material(state, runtime: Runtime[FlowContext]):
    kind = state["mastery_choice"]
    problems = validators.validate_study_material(
        kind, state["study_material"], _concepts(state), latex=runtime.context.sandbox.latex
    )
    label = MaterialKind(kind).label
    return outcome(state, "material", "study.generate", problems, "generate_study_material", f"The {label.lower()}")


def after_validate_study_material(state) -> str:
    return route_check(state, "material", ok="persist_study_material", retry="generate_study_material")


def persist_study_material(state, runtime: Runtime[FlowContext]):
    StudyMaterial.objects.update_or_create(
        lesson_id=state["lesson_id"], kind=state["mastery_choice"], defaults={"content": state["study_material"]}
    )
    set_stage(state["lesson_id"], Stage.READY)
    return {}

"""Writing the pair of sheets a learner who aced the quiz gets when they choose "sheets": the cheat sheet and the
revision sheet, written in parallel and grounded in the diagnostic's concepts.

One object asks the model for a sheet and checks it, as `ContentWriter` does for a page, so the same rules judge a
sheet however it was asked for. The single-sheet nodes (`generate_study_material` and its neighbours) stay for the
lessons already waiting at the old three-sheet choice and for another sheet later.
"""

from .context import FlowContext
from .prompts import StudyMaterialPrompt
from .questions import QuestionFinisher
from .schemas import MATERIAL_SCHEMAS
from .validators import StudyMaterialValidator

CHEAT_SHEET, REVISION_SHEET, PRACTICE_SHEET = "cheat_sheet", "revision_sheet", "practice_sheet"


class SheetKinds:
    #: what the "sheets" choice writes, in this order; also the only kinds that can be asked for now (the practice sheet
    #: is not offered any more, though the ones that exist can still be opened)
    CHOICE = (CHEAT_SHEET, REVISION_SHEET)

    @classmethod
    def of(cls, state: dict) -> tuple[str, ...]:
        """The sheets this run writes: the ones it was asked for, cheat sheet first, else both. A run queued before
        sheets could be asked for in pairs carried the one kind it wanted as `mastery_choice`."""
        asked = state.get("sheet_kinds")
        if not asked and state.get("extra_material") and state.get("mastery_choice"):
            return (state["mastery_choice"],)
        if not asked:
            return cls.CHOICE
        return tuple(kind for kind in (*cls.CHOICE, PRACTICE_SHEET) if kind in asked)

    @staticmethod
    def feedback_key(kind: str) -> str:
        return f"sheet:{kind}"


class SheetWriter:
    def __init__(self, ctx: FlowContext):
        self.ctx = ctx

    def sheet(self, data: dict, kind: str, feedback: list[str] | None) -> tuple[dict, list[str]]:
        """→ (the sheet, the validator's problems with it). The sheet is returned even when it has problems."""
        concepts = data.get("concepts") or []
        subject = data | {"kind": kind, "concepts": concepts}  # `grounding` rides along in `data` when there is one
        messages = StudyMaterialPrompt().messages(subject, feedback)
        output = self.ctx.invoke(data, "study.generate", messages, schema=MATERIAL_SCHEMAS[kind]).output
        material = output.model_dump(mode="json")
        if kind == "practice_sheet":
            material["questions"], _ = QuestionFinisher().finish(material["questions"])
        problems = StudyMaterialValidator(self.ctx.sandbox).validate(material, kind=kind, concepts=concepts)
        return material, problems

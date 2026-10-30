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

CHEAT_SHEET, REVISION_SHEET = "cheat_sheet", "revision_sheet"


class SheetKinds:
    #: what the "sheets" choice writes, in this order
    CHOICE = (CHEAT_SHEET, REVISION_SHEET)

    @staticmethod
    def feedback_key(kind: str) -> str:
        return f"sheet:{kind}"


class SheetWriter:
    def __init__(self, ctx: FlowContext):
        self.ctx = ctx

    def sheet(self, data: dict, kind: str, feedback: list[str] | None) -> tuple[dict, list[str]]:
        """→ (the sheet, the validator's problems with it). The sheet is returned even when it has problems."""
        concepts = data.get("concepts") or []
        subject = data | {"kind": kind, "concepts": concepts}
        messages = StudyMaterialPrompt().messages(subject, feedback)
        output = self.ctx.invoke(data, "study.generate", messages, schema=MATERIAL_SCHEMAS[kind]).output
        material = output.model_dump(mode="json")
        if kind == "practice_sheet":
            material["questions"], _ = QuestionFinisher().finish(material["questions"])
        problems = StudyMaterialValidator(self.ctx.sandbox).validate(material, kind=kind, concepts=concepts)
        return material, problems

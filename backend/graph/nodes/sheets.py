"""Study sheets: the mastery choice, and the pair of sheets written in parallel that three things share.

    await_choice → (choice_router)  lesson → assess_learner (as an Expert)
                                    sheets → plan_sheets → Send ×(cheat sheet ‖ revision sheet) → sheets_join → ready

`plan_sheets … sheets_join` is the one writer of sheets. The mastery choice reaches it, so does a lesson asked for as
sheets only (`intent=sheets`), and so does an extra sheet on a lesson that is already ready (the small graph, with
`extra_material` set, which leaves the lesson as it is). A run writes the kinds it was asked for (`sheet_kinds`),
grounded by `SheetGrounding`: the lesson's content, the quiz's concepts, or just the topic and level. `sheets_join`
sends back only the sheet that failed its rules, saves what was asked for when it passes, and gives up with a reason
when a sheet runs out of attempts (Retry then plans them again).
"""

from langgraph.graph import END
from langgraph.types import Send

from lessons.models import Stage, StudyMaterial

from ..context import FlowContext, NodeBudget
from ..grounding import SheetGrounding
from ..sheets import SheetKinds, SheetWriter
from .base import Node
from .branches import BranchBuilder
from .routers import Router

LESSON, SHEETS = "lesson", "sheets"


class ChoiceRouter(Router):
    """After await_choice: the Expert lesson, or the two sheets."""

    def __init__(self, *, lesson: str, sheets: str):
        self.lesson, self.sheets = lesson, sheets

    def __call__(self, state: dict) -> str:
        return self.lesson if state["mastery_choice"] == LESSON else self.sheets


class PlanSheetsNode(Node):
    """Starts the sheets: the lesson moves to writing them (unless it is a ready lesson getting another sheet, which
    stays ready), what they rest on is read once, and a Retry starts the sheets asked for from the beginning."""

    name = "plan_sheets"
    stage = Stage.GENERATING_MATERIAL

    def run(self, state: dict, ctx: FlowContext) -> dict:
        if not state.get("extra_material"):
            self.lesson(state).advance_to(Stage.GENERATING_MATERIAL)
        kinds = SheetKinds.of(state)
        grounding = SheetGrounding.of(state)
        keys = {SheetKinds.feedback_key(kind): None for kind in kinds}
        return {
            "sheet_kinds": list(kinds),
            "grounding": grounding.as_dict(),
            "concepts": grounding.concepts,
            "sheets": dict.fromkeys(kinds),
            "feedback": keys,
            "attempts": dict(keys),
        }


class SheetStatus:
    """Which sheets still need another attempt, and which ran out of attempts."""

    @classmethod
    def of(cls, state: dict) -> tuple[list[str], list[str]]:
        """→ (kinds to try again, kinds out of attempts that still have problems)."""
        retry, exhausted = [], []
        budget = NodeBudget.of(state, "study.generate").max_attempts
        for kind in SheetKinds.of(state):
            key = SheetKinds.feedback_key(kind)
            if not (state.get("feedback") or {}).get(key):
                continue
            (retry if (state.get("attempts") or {}).get(key, 0) < budget else exhausted).append(kind)
        return retry, exhausted

    @classmethod
    def sends(cls, state: dict, kinds=None) -> list[Send]:
        kinds = SheetKinds.of(state) if kinds is None else kinds
        feedback = state.get("feedback") or {}
        return [
            Send(
                "generate_sheet",
                BranchBuilder.of(state, key=kind, feedback=list(feedback.get(SheetKinds.feedback_key(kind)) or [])),
            )
            for kind in kinds
        ]


class PlanSheetsRouter(Router):
    """After plan_sheets: the sheets asked for are written at once."""

    def __call__(self, state: dict) -> list[Send]:
        return SheetStatus.sends(state)


class GenerateSheetNode(Node):
    """One sheet, written in parallel with the other."""

    name = "generate_sheet"
    stage = Stage.GENERATING_MATERIAL

    def run(self, state: dict, ctx: FlowContext) -> dict:
        kind = state["key"]
        material, problems = SheetWriter(ctx).sheet(state, kind, state.get("feedback"))
        key = SheetKinds.feedback_key(kind)
        # The latest version is kept even with problems: the join decides whether to try again.
        return {"sheets": {kind: material}, "feedback": {key: problems}, "attempts": {key: 1}}


class SheetsJoinNode(Node):
    """Saves the sheets when they pass, sends back the one that did not, or gives up when it is out of attempts."""

    name = "sheets_join"
    stage = Stage.GENERATING_MATERIAL

    COMPLETE, RETRY, FAILED = "complete", "retry", "failed"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        kinds = SheetKinds.of(state)
        retry, exhausted = SheetStatus.of(state)
        if exhausted:
            problems = [p for kind in exhausted for p in (state["feedback"].get(SheetKinds.feedback_key(kind)) or [])]
            return {
                "sheets_outcome": self.FAILED,
                "error": f"The study sheets still failed their checks: {'; '.join(problems[:4])}",
                "failed_node": "plan_sheets",
                "retry_keys": [SheetKinds.feedback_key(kind) for kind in kinds],
            }
        if retry:
            for kind in retry:
                ctx.events({
                    "type": "attempt", "node": "generate_sheet",
                    "attempt": state["attempts"].get(SheetKinds.feedback_key(kind), 0) + 1,
                    "reason": state["feedback"][SheetKinds.feedback_key(kind)][0],
                })  # fmt: skip
            return {"sheets_outcome": self.RETRY}
        for kind in kinds:
            StudyMaterial.objects.update_or_create(
                lesson_id=state["lesson_id"], kind=kind, defaults={"content": state["sheets"][kind]}
            )
        if not state.get("extra_material"):
            self.lesson(state).advance_to(Stage.READY)
        return {"sheets_outcome": self.COMPLETE}


class SheetsRouter(Router):
    """After sheets_join: send back only the sheet that failed, finish, or give up."""

    def __init__(self, on_fail: str = "mark_failed"):
        self.on_fail = on_fail

    def __call__(self, state: dict):
        outcome = state["sheets_outcome"]
        if outcome == SheetsJoinNode.FAILED:
            return self.on_fail
        if outcome == SheetsJoinNode.RETRY:
            retry, _ = SheetStatus.of(state)
            return SheetStatus.sends(state, retry)
        return END

"""The way into a lesson, for a learner who did not take the quick check (docs/architecture/lesson-graph.md).

    load_context → entry_router → assess_from_source → level_gate → (plan_prerequisites → validate_prerequisites) →
    intent_router → plan_lesson

The quick check keeps its own road (generate_diagnostic … assess_learner); both roads meet at `level_gate`. The three
junction nodes (`entry_router`, `level_gate`, `intent_router`) only carry a decision: the decision itself is a router
class, so it is table-tested without a graph.
"""

from lessons.models import Stage

from ..assessment import AssessmentRequest, AssessmentSources
from ..context import FlowContext
from ..errors import RunFailed
from ..levels import Level, LevelScheme
from ..prompts import PlanPrerequisitesPrompt
from ..schemas import PrerequisiteList
from ..validators import PrerequisiteListValidator, Validator
from .base import LLMNode, Node, ValidateNode
from .routers import Router

DIAGNOSTIC = "diagnostic"


class Junction(Node):
    """A point where the graph decides where to go: it changes nothing, its conditional edge decides."""

    def run(self, state: dict, ctx: FlowContext) -> dict:
        return {}


class EntryRouterNode(Junction):
    name = "entry_router"


class LevelGateNode(Junction):
    name = "level_gate"


class IntentRouterNode(Junction):
    name = "intent_router"


class EntryRouter(Router):
    """After load_context: the quick check, or a source that needs no quiz. A thread from before self-rating has no
    `entry`, and it is a quick check."""

    def __init__(self, diagnostic: str = "generate_diagnostic", rated: str = "assess_from_source"):
        self.diagnostic, self.rated = diagnostic, rated

    def __call__(self, state: dict) -> str:
        return self.diagnostic if state.get("entry", DIAGNOSTIC) == DIAGNOSTIC else self.rated


class LevelGate(Router):
    """After an assessment: a Beginner who took no quiz has had nothing tested, so their prerequisites are planned
    (`prerequisites.plan`). A quick check already found them, and any other level starts on the lesson."""

    def __init__(self, plan: str = "plan_prerequisites", otherwise: str = "intent_router"):
        self.plan, self.otherwise = plan, otherwise

    def __call__(self, state: dict) -> str:
        if state.get("entry", DIAGNOSTIC) == DIAGNOSTIC or state.get("prerequisites_to_cover"):
            return self.otherwise
        level = LevelScheme.level_of(state["assessment"])
        return self.plan if level is Level.BEGINNER else self.otherwise


class IntentRouter(Router):
    """Where each thing a learner can ask for goes. Only a lesson is wired; sheets from a topic arrive later, as one
    more entry here."""

    def __init__(self, destinations: dict[str, str]):
        self.destinations = destinations

    def __call__(self, state: dict) -> str:
        intent = state.get("intent", "lesson")
        if intent not in self.destinations:
            raise RunFailed(f"Asking for {intent!r} is not available yet.")
        return self.destinations[intent]


class AssessFromSourceNode(Node):
    """The level of a lesson with no quiz, in code: the source turns what the learner gave into the one assessment."""

    name = "assess_from_source"
    stage = Stage.GENERATING_LESSON

    def run(self, state: dict, ctx: FlowContext) -> dict:
        source = AssessmentSources.for_key(state["entry"])
        assessment = source.assess(AssessmentRequest(self_rating_halves=state.get("self_rating_halves")))
        level = LevelScheme.level_of(assessment)
        self.lesson(state).advance_to(
            Stage.GENERATING_LESSON,
            route="lesson",
            prerequisites_to_cover=[],
            assessment=assessment,
            level=level.value,
            level_source=assessment["source"],
        )
        return {"assessment": assessment, "route": "lesson", "prerequisites_to_cover": [], "level_source": source.key}


class PlanPrerequisitesNode(LLMNode):
    name = "plan_prerequisites"
    stage = Stage.GENERATING_LESSON
    node_key = "prerequisites.plan"
    prompt = PlanPrerequisitesPrompt()
    schema = PrerequisiteList
    feedback_key = "prerequisites"

    def to_state(self, output: PrerequisiteList, state: dict, ctx: FlowContext) -> dict:
        return {"prerequisite_plan": output.model_dump(mode="json"), "attempts": {"prerequisites": 1}}


class ValidatePrerequisitesNode(ValidateNode):
    name = "validate_prerequisites"
    stage = Stage.GENERATING_LESSON
    node_key = "prerequisites.plan"
    feedback_key = "prerequisites"
    retry_node = "plan_prerequisites"
    label = "The list of prerequisites"

    def validator(self, state: dict, ctx: FlowContext) -> Validator:
        return PrerequisiteListValidator()

    def subject(self, state: dict) -> dict:
        return state["prerequisite_plan"]

    def context(self, state: dict) -> dict:
        return {"topic": state["topic"]}

    def outcome(self, state: dict, problems: list[str], ctx: FlowContext) -> dict:
        """Once the list is good it becomes the lesson's prerequisites, which the plan must teach on its first page."""
        update = super().outcome(state, problems, ctx)
        if problems:
            return update
        items = state["prerequisite_plan"]["prerequisites"]
        assessment = {**state["assessment"], "prerequisites_to_cover": [item["name"] for item in items]}
        self.lesson(state).record(prerequisites_to_cover=items, assessment=assessment)
        return update | {"prerequisites_to_cover": items, "assessment": assessment}

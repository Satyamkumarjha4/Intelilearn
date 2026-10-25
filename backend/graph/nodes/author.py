"""Stage B: author the lesson.

    plan_lesson → validate_plan → Send ×4 (write_page ×3 ‖ write_test) → authored_join (re-sends only the failed items)
    → plan_interactives → validate_interactive_plan → Send per spec (find_media ‖ build_interactive) → widgets_join
    → alignment_judge → Send fix_item (only the flagged items) → alignment_judge … → Stage C

Items that run in parallel receive a `Branch` (shared context plus the item) and write their result under a key of
the state with a reducer; the join node then decides, from the attempts and the validator's problems, whether to
send the failing items again, accept them with a warning, or move on.
"""

from langgraph.types import Send

from lessons.models import Stage

from ..alignment import AlignmentPolicy
from ..authoring import ContentWriter
from ..context import FlowContext, NodeBudget
from ..prompts import AlignmentPrompt, PlanInteractivesPrompt, PlanLessonPrompt
from ..schemas import MEDIA_KINDS, PAGE_KEYS, AlignmentReport, InteractivePlan, LessonPlan
from ..validators import InteractivePlanValidator, PlanValidator, Validator
from .authoring_media import MediaAssets
from .base import LLMNode, Node, ValidateNode
from .branches import BranchBuilder
from .media_agent import MediaFinder


class PlanLessonNode(LLMNode):
    name = "plan_lesson"
    stage = Stage.GENERATING_LESSON
    node_key = "lesson.plan"
    prompt = PlanLessonPrompt()
    schema = LessonPlan
    feedback_key = "plan"

    def to_state(self, output: LessonPlan, state: dict, ctx: FlowContext) -> dict:
        return {"plan": output.model_dump(mode="json"), "attempts": {"plan": 1}}


class ValidatePlanNode(ValidateNode):
    name = "validate_plan"
    stage = Stage.GENERATING_LESSON
    node_key = "lesson.plan"
    feedback_key = "plan"
    retry_node = "plan_lesson"
    label = "The lesson plan"

    def validator(self, state: dict, ctx: FlowContext) -> Validator:
        return PlanValidator()

    def subject(self, state: dict) -> dict:
        return state["plan"]

    def context(self, state: dict) -> dict:
        return {"settings": state["settings"], "prerequisites_to_cover": state.get("prerequisites_to_cover") or []}

    def outcome(self, state: dict, problems: list[str], ctx: FlowContext) -> dict:
        if not problems:
            plan = state["plan"]
            self.lesson(state).record(plan=plan, title=plan["title"][:200], level=plan["level"])
        return super().outcome(state, problems, ctx)


class AuthoringStatus:
    """Which of the pages and the test still need another attempt, and which ran out of attempts."""

    ITEMS = (*PAGE_KEYS, "test")

    @staticmethod
    def feedback_key(key: str) -> str:
        return "test" if key == "test" else f"page:{key}"

    @staticmethod
    def node_key(key: str) -> str:
        return "test.generate" if key == "test" else "page.generate"

    @classmethod
    def of(cls, state: dict) -> tuple[list[str], list[str]]:
        """→ (keys to try again, keys out of attempts that still have problems)."""
        retry, exhausted = [], []
        for key in cls.ITEMS:
            item = cls.feedback_key(key)
            if not (state.get("feedback") or {}).get(item):
                continue
            attempts = (state.get("attempts") or {}).get(item, 0)
            budget = NodeBudget.of(state, cls.node_key(key)).max_attempts
            (retry if attempts < budget else exhausted).append(key)
        return retry, exhausted

    @classmethod
    def sends(cls, state: dict, keys=ITEMS, fix: dict[str, list[str]] | None = None) -> list[Send]:
        sends = []
        for key in keys:
            feedback = (fix or {}).get(key) or list((state.get("feedback") or {}).get(cls.feedback_key(key)) or [])
            sends.append(
                Send(
                    "write_test" if key == "test" else "write_page", BranchBuilder.of(state, key=key, feedback=feedback)
                )
            )
        return sends


class WritePageNode(Node):
    """One of the three content pages, written in parallel with the others and the test."""

    name = "write_page"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        key = state["key"]
        page, problems = ContentWriter(ctx).page(state, key, state.get("feedback"))
        # The latest version is kept even with problems: authored_join decides whether to try again or accept it.
        return {"pages": {key: page}, "feedback": {f"page:{key}": problems}, "attempts": {f"page:{key}": 1}}


class WriteTestNode(Node):
    name = "write_test"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        test, problems = ContentWriter(ctx).final_test(state, state.get("feedback"))
        return {"final_test": test, "feedback": {"test": problems}, "attempts": {"test": 1}}


class AuthoredJoinNode(Node):
    name = "authored_join"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        retry, exhausted = AuthoringStatus.of(state)
        for key in retry:
            problems = (state.get("feedback") or {}).get(AuthoringStatus.feedback_key(key)) or [""]
            node = "write_test" if key == "test" else f"write_page:{key}"
            ctx.events({"type": "attempt", "node": node, "reason": problems[0]})
        if retry:
            return {}
        warnings: list[str] = []
        for key in exhausted:
            problems = state["feedback"][AuthoringStatus.feedback_key(key)]
            name = "final test" if key == "test" else f"{key} page"
            warnings += ctx.warn(f"The {name} was kept despite: {'; '.join(problems[:3])}")
        self.lesson(state).record(pages=state["pages"], final_test=state["final_test"])
        return {"warnings": warnings}


class PlanInteractivesNode(LLMNode):
    name = "plan_interactives"
    stage = Stage.GENERATING_LESSON
    node_key = "interactive.plan"
    prompt = PlanInteractivesPrompt()
    schema = InteractivePlan
    feedback_key = "interactive_plan"

    def to_state(self, output: InteractivePlan, state: dict, ctx: FlowContext) -> dict:
        return {"interactive_plan": output.model_dump(mode="json"), "attempts": {"interactive_plan": 1}}


class UsableSpecs:
    """Degrade: the specs that are individually valid, at most the maximum per page."""

    @staticmethod
    def of(plan: dict, pages: dict, settings: dict) -> list[dict]:
        kept, per_page, seen = [], {}, set()
        for spec in plan["specs"]:
            sections = {s["id"] for s in (pages.get(spec["page"]) or {}).get("sections", [])}
            valid = (
                spec["id"] not in seen
                and InteractivePlanValidator.ID.fullmatch(spec["id"])
                and spec["anchor_section"] in sections
                and (spec["kind"] not in MEDIA_KINDS or spec.get("media_query", "").strip())
                and per_page.get(spec["page"], 0) < settings.get("max_interactives_per_page", 3)
            )
            if valid:
                per_page[spec["page"]] = per_page.get(spec["page"], 0) + 1
                seen.add(spec["id"])
                kept.append(spec)
        return kept


class ValidateInteractivePlanNode(Node):
    """Unlike the other validators it never fails the run: out of attempts, it keeps what is usable and warns."""

    name = "validate_interactive_plan"
    stage = Stage.GENERATING_LESSON

    def run(self, state: dict, ctx: FlowContext) -> dict:
        plan = state["interactive_plan"]
        problems = InteractivePlanValidator().validate(plan, pages=state["pages"], settings=state["settings"])
        if not problems:
            return {"feedback": {"interactive_plan": []}}
        if self.attempts(state, "interactive_plan") < NodeBudget.of(state, "interactive.plan").max_attempts:
            ctx.events({"type": "attempt", "node": "plan_interactives", "reason": problems[0]})
            return {"feedback": {"interactive_plan": problems}}
        kept = UsableSpecs.of(plan, state["pages"], state["settings"])
        dropped = len(plan["specs"]) - len(kept)
        warnings = ctx.warn(f"Interactive plan kept {len(kept)} of {len(plan['specs'])} items ({dropped} invalid)")
        return {"interactive_plan": {"specs": kept}, "feedback": {"interactive_plan": []}, "warnings": warnings}


class WidgetStatus:
    """Which widgets (interactives and media) still need another attempt, and which ran out of attempts."""

    @staticmethod
    def feedback_key(spec_id: str) -> str:
        return f"widget:{spec_id}"

    @classmethod
    def of(cls, state: dict) -> tuple[list[str], list[str]]:
        retry, exhausted = [], []
        budget = NodeBudget.of(state, "interactive.generate").max_attempts
        for spec in state["interactive_plan"]["specs"]:
            key = cls.feedback_key(spec["id"])
            if not (state.get("feedback") or {}).get(key):
                continue
            (retry if (state.get("attempts") or {}).get(key, 0) < budget else exhausted).append(spec["id"])
        return retry, exhausted

    @classmethod
    def sends(
        cls, state: dict, spec_ids: set[str] | None = None, fix: dict[str, list[str]] | None = None
    ) -> list[Send]:
        sends = []
        for spec in state["interactive_plan"]["specs"]:
            if spec_ids is not None and spec["id"] not in spec_ids:
                continue
            feedback = (fix or {}).get(spec["id"]) or list(
                (state.get("feedback") or {}).get(cls.feedback_key(spec["id"])) or []
            )
            kind = (state.get("widget_kinds") or {}).get(spec["id"], spec["kind"])
            target = "find_media" if kind in MEDIA_KINDS else "build_interactive"
            sends.append(
                Send(target, BranchBuilder.of(state, key=spec["id"], item=spec | {"kind": kind}, feedback=feedback))
            )
        return sends


class BuildInteractiveNode(Node):
    name = "build_interactive"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        spec = state["item"]
        component, problems = ContentWriter(ctx).component(state, spec, state.get("feedback"))
        key = WidgetStatus.feedback_key(spec["id"])
        update: dict = {"feedback": {key: problems}, "attempts": {key: 1}}
        if not problems:
            update["interactives"] = {spec["id"]: component}
        return update


class FindMediaNode(Node):
    """A real image or GIF for a spec. Nothing suitable → the spec is drawn as an SVG diagram instead, so the lesson
    never has an empty slot."""

    name = "find_media"

    def __init__(self, finder: MediaFinder | None = None):
        self._finder = finder

    @property
    def finder(self) -> MediaFinder:
        self._finder = self._finder or MediaFinder()
        return self._finder

    def run(self, state: dict, ctx: FlowContext) -> dict:
        spec = state["item"]
        key = WidgetStatus.feedback_key(spec["id"])
        ref = self.finder.find(ctx, state, spec, state.get("feedback"))
        if ref:
            return {"media": {spec["id"]: ref}, "feedback": {key: []}, "attempts": {key: 1}}
        warnings = ctx.warn(f'No suitable {spec["kind"]} found for "{spec["id"]}": drawing an SVG diagram instead')
        component, problems = ContentWriter(ctx).component(state, spec | {"kind": "svg_diagram"}, [])
        update = {"widget_kinds": {spec["id"]: "svg_diagram"}, "feedback": {key: problems}, "attempts": {key: 1},
                  "warnings": warnings}  # fmt: skip
        if not problems:
            update["interactives"] = {spec["id"]: component}
        return update


class WidgetsJoinNode(Node):
    name = "widgets_join"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        retry, exhausted = WidgetStatus.of(state)
        if retry:
            return {}
        warnings: list[str] = []
        for spec_id in exhausted:
            warnings += ctx.warn(f'Dropped the interactive "{spec_id}": it kept failing the code checks')
        MediaAssets.persist(state["lesson_id"], state.get("media") or {})
        kinds = state.get("widget_kinds") or {}
        specs = [
            spec | {"kind": kinds.get(spec["id"], spec["kind"]), "dropped": spec["id"] in exhausted}
            for spec in state["interactive_plan"]["specs"]
        ]
        self.lesson(state).record(interactive_plan={"specs": specs})
        return {"warnings": warnings}


class AlignmentJudgeNode(LLMNode):
    """The gate before any document code is written. Out of rounds with a major issue left, the run fails."""

    name = "alignment_judge"
    stage = Stage.GENERATING_LESSON
    node_key = "alignment.judge"
    prompt = AlignmentPrompt()
    schema = AlignmentReport

    def __init__(self, policy: AlignmentPolicy | None = None):
        self.policy = policy or AlignmentPolicy()

    def to_state(self, output: AlignmentReport, state: dict, ctx: FlowContext) -> dict:
        rounds = self.attempts(state, "alignment") + 1
        verdict = self.policy.decide(output, state=state, round_number=rounds)
        update: dict = {"alignment": verdict.report, "attempts": {"alignment": 1}}
        if verdict.decision == "fix":
            ctx.events({
                "type": "attempt", "node": "alignment_judge", "attempt": rounds + 1,
                "reason": f"{len(verdict.fixable)} item(s) to fix: {verdict.fixable[0]['problem']}",
            })  # fmt: skip
        elif verdict.decision == "accept":
            update["warnings"] = ctx.warn(verdict.warnings[0])
        elif verdict.decision == "pass":
            update["warnings"] = verdict.warnings
        else:
            update |= {"error": verdict.error, "failed_node": "alignment_judge", "retry_keys": ["alignment"]}
        return update


class FixItemNode(Node):
    """Redoes one flagged item with the judge's instruction. A fix that fails its own checks keeps the old version."""

    name = "fix_item"

    def __init__(self, finder: MediaFinder | None = None):
        self._finder = finder

    @property
    def finder(self) -> MediaFinder:
        self._finder = self._finder or MediaFinder()
        return self._finder

    def run(self, state: dict, ctx: FlowContext) -> dict:
        issue = state["item"]
        feedback = [f"A reviewer flagged: {issue['problem']}", f"Fix: {issue['fix_instruction']}"]
        target, target_id = issue["target"], issue["target_id"]
        writer = ContentWriter(ctx)
        if target == "page":
            page, problems = writer.page(state, target_id, feedback)
            return self.kept(ctx, f"the {target_id} page", problems) or {"pages": {target_id: page}}
        if target == "final_test":
            feedback[0] += f" (question {target_id})"
            test, problems = writer.final_test(state, feedback)
            return self.kept(ctx, "the test", problems) or {"final_test": test}
        spec = next(s for s in state["interactive_plan"]["specs"] if s["id"] == target_id)
        if target == "media" and spec["kind"] in MEDIA_KINDS:
            ref = self.finder.find(ctx, state, spec, feedback)
            if ref:
                return {"media": {target_id: ref}}
            return {"warnings": ctx.warn(f'Could not find better media for "{target_id}"')}
        component, problems = writer.component(state, spec, feedback)
        return self.kept(ctx, f'"{target_id}"', problems) or {"interactives": {target_id: component}}

    @staticmethod
    def kept(ctx: FlowContext, what: str, problems: list[str]) -> dict | None:
        """The warning to return when the fix itself was no good (the old version stays), else None."""
        if problems:
            return {"warnings": ctx.warn(f"Could not apply the review fix to {what}: {problems[0]}")}
        return None

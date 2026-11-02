"""Stage B: author the lesson.

    plan_lesson → validate_plan → plan_batches → Send ×(3 pages ‖ one per batch of test questions) → authored_join
    (re-sends only the failed items, plans unfilled test cells again) → plan_interactives
    → validate_interactive_plan → Send per spec (find_media ‖ build_interactive) → widgets_join
    → alignment_judge → Send fix_item (only the flagged items) → alignment_judge … → Stage C

Items that run in parallel receive a `Branch` (shared context plus the item) and write their result under a key of
the state with a reducer; the join node then decides, from the attempts and the validator's problems, whether to
send the failing items again, accept them with a warning, or move on.
"""

import uuid

from langgraph.types import Send

from lessons.bank import QuestionBank
from lessons.models import Stage

from ..alignment import AlignmentPolicy
from ..authoring import ContentWriter
from ..context import FlowContext, NodeBudget
from ..levels import LevelScheme
from ..prompts import AlignmentPrompt, PlanInteractivesPrompt, PlanLessonPrompt
from ..questions import LessonTestBlueprint
from ..schemas import MEDIA_KINDS, PAGE_KEYS, AlignmentReport, FinalTest, InteractivePlan, LessonPlan
from ..shapes import LessonShapes
from ..validators import InteractivePlanValidator, PlanValidator, Validator
from .authoring_media import MediaAssets
from .base import LLMNode, Node, ValidateNode
from .branches import BranchBuilder
from .media_agent import MediaFinder
from .questions import QuestionRound


class PlanLessonNode(LLMNode):
    name = "plan_lesson"
    stage = Stage.GENERATING_LESSON
    node_key = "lesson.plan"
    prompt = PlanLessonPrompt()
    schema = LessonPlan
    feedback_key = "plan"

    def to_state(self, output: LessonPlan, state: dict, ctx: FlowContext) -> dict:
        # The level is the learner's, found by the quiz or the rating: the model does not get to change it.
        level = LevelScheme.level_of(state["assessment"])
        return {
            "plan": LevelScheme.stamp(output.model_dump(mode="json") | {"level": level.value}),
            "blueprint": LessonTestBlueprint.for_topic(output.quantitative).to_json(),
            "question_round": 0,  # a new plan starts the test from the beginning
            "accepted": {},
            "attempts": {"plan": 1},
        }


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
        return {
            "prerequisites_to_cover": state.get("prerequisites_to_cover") or [],
            "shape": LessonShapes.of(state["assessment"]),
        }

    def outcome(self, state: dict, problems: list[str], ctx: FlowContext) -> dict:
        if not problems:
            plan = state["plan"]
            self.lesson(state).record(
                plan=plan,
                title=plan["title"][:200],
                level=LevelScheme.level_of(plan).value,
                test_blueprint=state["blueprint"],
            )
        return super().outcome(state, problems, ctx)


class AuthoringStatus:
    """Which of the pages still need another attempt, and which ran out of attempts. (The test's questions have their
    own bookkeeping, `QuestionRound`.)"""

    ITEMS = PAGE_KEYS

    @staticmethod
    def feedback_key(key: str) -> str:
        return f"page:{key}"

    @classmethod
    def of(cls, state: dict) -> tuple[list[str], list[str]]:
        """→ (keys to try again, keys out of attempts that still have problems)."""
        retry, exhausted = [], []
        budget = NodeBudget.of(state, "page.generate").max_attempts
        for key in cls.ITEMS:
            item = cls.feedback_key(key)
            if not (state.get("feedback") or {}).get(item):
                continue
            attempts = (state.get("attempts") or {}).get(item, 0)
            (retry if attempts < budget else exhausted).append(key)
        return retry, exhausted

    @classmethod
    def sends(cls, state: dict, keys=ITEMS, fix: dict[str, list[str]] | None = None) -> list[Send]:
        sends = []
        for key in keys:
            feedback = (fix or {}).get(key) or list((state.get("feedback") or {}).get(cls.feedback_key(key)) or [])
            sends.append(Send("write_page", BranchBuilder.of(state, key=key, feedback=feedback)))
        return sends


class WritePageNode(Node):
    """One of the three content pages, written in parallel with the others and the test's batches."""

    name = "write_page"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        key = state["key"]
        page, problems = ContentWriter(ctx).page(state, key, state.get("feedback"))
        # The latest version is kept even with problems: the join decides whether to try again or accept it.
        return {"pages": {key: page}, "feedback": {f"page:{key}": problems}, "attempts": {f"page:{key}": 1}}


class AuthoredJoinNode(Node):
    """Waits for the pages and the test's batches. Re-sends what failed, plans the test's unfilled cells again, and when
    everything has settled saves the pages and the test (and the test's questions on the record). A lesson test must
    have all ten cells filled: if it cannot be, the run fails instead of keeping a test that is not the blueprint."""

    name = "authored_join"

    def __init__(self, questions: QuestionRound | None = None, bank: QuestionBank | None = None):
        self.questions = questions or QuestionRound()
        self.bank = bank or QuestionBank()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        retry, exhausted = AuthoringStatus.of(state)
        result = self.questions.close(state, ctx)
        if result.outcome in (QuestionRound.PENDING, QuestionRound.REPLAN, QuestionRound.SHORT):
            return result.update  # pages that need another go wait for the questions' round to settle
        for key in retry:
            problems = (state.get("feedback") or {}).get(AuthoringStatus.feedback_key(key)) or [""]
            ctx.events({"type": "attempt", "node": f"write_page:{key}", "reason": problems[0]})
        if result.outcome == QuestionRound.RETRY or retry:
            return result.update
        warnings: list[str] = list(result.update["warnings"])
        for key in exhausted:
            problems = state["feedback"][AuthoringStatus.feedback_key(key)]
            warnings += ctx.warn(f"The {key} page was kept despite: {'; '.join(problems[:3])}")
        accepted = result.update["accepted"]
        blueprint = LessonTestBlueprint.from_json(state["blueprint"])
        questions = [accepted[str(cell.index)] for cell in blueprint.cells]
        stored = self.bank.add(state["lesson_id"], self.batch(ctx), questions)
        test = {"title": FinalTest(questions=[]).title, "questions": stored}
        self.bank.set_first_set(state["lesson_id"], stored)
        self.lesson(state).record(pages=state["pages"])
        return result.update | {"final_test": test, "warnings": warnings}

    @staticmethod
    def batch(ctx: FlowContext) -> uuid.UUID | None:
        """The run that wrote the questions, for the record."""
        try:
            return uuid.UUID(str(ctx.run_id))
        except ValueError:
            return None


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

    def __init__(self, finder: MediaFinder | None = None, bank: QuestionBank | None = None):
        self._finder = finder
        self.bank = bank or QuestionBank()

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
            question, problems = writer.question(state, target_id, feedback)
            return self.kept(ctx, "the test", problems) or {
                "final_test": self.replaced(state, ctx, target_id, question)
            }
        spec = next(s for s in state["interactive_plan"]["specs"] if s["id"] == target_id)
        if target == "media" and spec["kind"] in MEDIA_KINDS:
            ref = self.finder.find(ctx, state, spec, feedback)
            if ref:
                return {"media": {target_id: ref}}
            return {"warnings": ctx.warn(f'Could not find better media for "{target_id}"')}
        component, problems = writer.component(state, spec, feedback)
        return self.kept(ctx, f'"{target_id}"', problems) or {"interactives": {target_id: component}}

    def replaced(self, state: dict, ctx: FlowContext, question_id: str, question: dict) -> dict:
        """The test with one question written again: the old one is retired on the record, the new one added."""
        test = state["final_test"]
        old = next(q for q in test["questions"] if q["id"] == question_id)
        (stored,) = self.bank.add(state["lesson_id"], AuthoredJoinNode.batch(ctx), [question])
        if old.get("question_id") and old["question_id"] != stored["question_id"]:
            self.bank.replace_in_first_set(state["lesson_id"], old["question_id"], stored)  # retires the old row
        return {**test, "questions": [stored if q["id"] == question_id else q for q in test["questions"]]}

    @staticmethod
    def kept(ctx: FlowContext, what: str, problems: list[str]) -> dict | None:
        """The warning to return when the fix itself was no good (the old version stays), else None."""
        if problems:
            return {"warnings": ctx.warn(f"Could not apply the review fix to {what}: {problems[0]}")}
        return None

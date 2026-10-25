"""Stage C: build and verify the lesson document.

prepare_build → Send ×3 compile_page (page.compile → code_fix_loop) → assemble_document → render_check
→ persist_lesson, or Send repair_page / repair_component for what broke, then assemble again. If repairs run out,
the broken pages fall back to the template layout (a broken interactive is dropped), with a warning.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from lessons.document import LessonData
from lessons.models import Lesson, MediaAsset, Stage

from ..builder_base import GraphBuilder
from ..codegen import DocumentAssembler
from ..context import FlowContext, NodeBudget
from ..prompts import CompilePagePrompt, RepairCodePrompt
from ..rendering import PageParts, RenderPolicy
from ..sanitizer import CodeSanitizer
from ..schemas import PAGE_KEYS
from .authoring_media import MediaAssets
from .base import Node
from .routers import Router

assembler = DocumentAssembler()

# --- code_fix_loop: sanitize → static_check → (repair_code → sanitize …) ------------------------------------------


class FixState(TypedDict, total=False):
    code: str
    contract: str
    required: list[str]
    components: list[str]
    asset_ids: list[str]
    errors: list[str]
    attempts: int
    max_attempts: int
    data: dict  # the lesson context for the gateway (snapshot, lesson id)
    ok: bool


class SanitizeNode(Node):
    name = "sanitize"

    def run(self, state: FixState, ctx: FlowContext) -> dict:
        return {"code": CodeSanitizer().sanitize(state["code"])}


class StaticCheckNode(Node):
    name = "static_check"

    def run(self, state: FixState, ctx: FlowContext) -> dict:
        check = ctx.sandbox.check_code(
            state["code"],
            required=state["required"],
            components=state.get("components", []),
            asset_ids=state.get("asset_ids", []),
        )
        return {"errors": list(check.errors), "ok": not check.errors}


class RepairCodeNode(Node):
    name = "repair_code"

    def run(self, state: FixState, ctx: FlowContext) -> dict:
        attempts = state.get("attempts", 0)
        ctx.events({"type": "attempt", "node": "code_fix_loop", "attempt": attempts + 1, "reason": state["errors"][0]})
        messages = RepairCodePrompt().messages(
            {"code": state["code"], "errors": state["errors"], "contract": state["contract"]}
        )
        code = ctx.invoke(state["data"], "code.repair", messages).output
        return {"code": code, "attempts": attempts + 1}


class FixRouter(Router):
    def __call__(self, state: FixState) -> str:
        if state["ok"]:
            return END
        return "repair_code" if state.get("attempts", 0) < state["max_attempts"] else END


class CodeFixLoopBuilder(GraphBuilder):
    state_schema = FixState

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (SanitizeNode(), StaticCheckNode(), RepairCodeNode()):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph) -> None:
        graph.add_edge(START, "sanitize")
        graph.add_edge("sanitize", "static_check")
        graph.add_conditional_edges("static_check", FixRouter(), ["repair_code", END])
        graph.add_edge("repair_code", "sanitize")


class CodeFixer:
    """Runs the code-fix loop on one piece of code → (the code, the errors it still has; empty means it passes)."""

    def __init__(self, builder: GraphBuilder | None = None):
        self.graph = (builder or CodeFixLoopBuilder()).build()

    def fix(self, ctx: FlowContext, data: dict, code: str, *, contract: str, required: list[str],
            components=(), asset_ids=()) -> tuple[str, list[str]]:  # fmt: skip
        result = self.graph.invoke(
            {
                "code": code, "contract": contract, "required": required, "components": list(components),
                "asset_ids": list(asset_ids), "attempts": 0, "data": data,
                "max_attempts": NodeBudget.of(data, "code.repair").max_attempts,
            },
            context=ctx,
        )  # fmt: skip
        return result["code"], ([] if result["ok"] else result["errors"])


# --- the nodes ----------------------------------------------------------------------------------------------------


class PrepareBuildNode(Node):
    """The entry of Stage C. A node of its own so the alignment judge's exit is one name; the fan-out is its router."""

    name = "prepare_build"
    stage = Stage.GENERATING_LESSON

    def run(self, state: dict, ctx: FlowContext) -> dict:
        return {}


class CompilePageNode(Node):
    """One content page as a React component. Content is data (`LESSON.pages.<key>`): the page renders it."""

    name = "compile_page"

    def __init__(self, fixer: CodeFixer | None = None):
        self._fixer = fixer

    @property
    def fixer(self) -> CodeFixer:
        self._fixer = self._fixer or CodeFixer()
        return self._fixer

    def run(self, data: dict, ctx: FlowContext) -> dict:
        key = data["key"]
        components, figures, placements = PageParts.of(data, key)
        subject = data | {"key": key, "components": components, "figures": figures}
        draft = ctx.invoke(data, "page.compile", CompilePagePrompt().messages(subject)).output
        code, errors = self.fixer.fix(
            ctx, data, draft,
            contract=assembler.page_contract(key, [c["name"] for c in components]),
            required=[assembler.page_component(key)],
            components=PageParts.component_names(data),
            asset_ids=PageParts.asset_ids(data),
        )  # fmt: skip
        if errors:
            warnings = ctx.warn(f"The {key} page uses the standard layout: generated code kept failing ({errors[0]})")
            return {"page_code": {key: assembler.template_page(key, placements)}, "warnings": warnings}
        return {"page_code": {key: code}}


class AssembleDocumentNode(Node):
    name = "assemble_document"
    stage = Stage.GENERATING_LESSON

    def run(self, state: dict, ctx: FlowContext) -> dict:
        pages = dict(state.get("page_code") or {})
        components = PageParts.component_code(state)
        assets = PageParts.asset_ids(state)
        document = assembler.assemble(components, pages)
        check = ctx.sandbox.check_code(document, required=["LessonDocument"], asset_ids=assets)
        if not check.errors:
            return {"document_code": document}
        # Each part passed on its own, so this is a clash between parts: fall back to template pages, once.
        specs = (state.get("interactive_plan") or {}).get("specs", [])
        built, media = set(state.get("interactives") or {}), state.get("media") or {}
        pages |= {
            key: assembler.template_page(key, assembler.placements_for(key, specs, built, media)) for key in PAGE_KEYS
        }
        document = assembler.assemble(components, pages)
        check = ctx.sandbox.check_code(document, required=["LessonDocument"], asset_ids=assets)
        if check.errors:
            return {
                "error": f"The lesson document does not pass the code checks: {check.errors[0]}",
                "failed_node": "assemble_document", "retry_keys": ["render"], "document_code": None,
            }  # fmt: skip
        return {
            "document_code": document, "page_code": {k: pages[k] for k in PAGE_KEYS},
            "warnings": ctx.warn("Pages use the standard layout: the generated pages clashed"),
        }  # fmt: skip


class RenderCheckNode(Node):
    name = "render_check"
    stage = Stage.GENERATING_LESSON

    def __init__(self, policy: RenderPolicy | None = None):
        self.policy = policy or RenderPolicy()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        data = LessonData.build(state, media_url=lambda asset_id: f"https://media.invalid/{asset_id}")
        report = ctx.sandbox.render_check(
            state["document_code"], data, pages=list(PAGE_KEYS), media_files=self.media_files(state)
        )
        rounds = self.attempts(state, "render") + 1
        verdict = self.policy.decide(report, state=state, round_number=rounds)
        update: dict = {"render_report": verdict.report, "attempts": {"render": 1}}
        if verdict.decision == "pass":
            return update
        ctx.events({"type": "attempt", "node": "render_check", "attempt": rounds + 1,
                    "reason": verdict.problems[0] if verdict.problems else ""})  # fmt: skip
        if verdict.decision == "fallback":
            fallback = dict(verdict.update)
            note = fallback.pop("_warning")
            update |= fallback | {"warnings": ctx.warn(note)}
        elif verdict.decision == "fail":
            update |= {
                "error": "The lesson failed the sandbox render check: " + "; ".join(verdict.problems[:3]),
                "failed_node": "assemble_document", "retry_keys": ["render"],
            }  # fmt: skip
        return update

    @staticmethod
    def media_files(state: dict) -> dict[str, str]:
        from pathlib import Path

        from django.conf import settings

        root = Path(settings.MEDIA_ROOT)
        return {ref["asset_id"]: str(root / ref["file"]) for ref in (state.get("media") or {}).values()}


class RepairPageNode(Node):
    """One page that broke in the browser: the model sees the errors, then the same checks as a fresh page."""

    name = "repair_page"

    def __init__(self, fixer: CodeFixer | None = None):
        self._fixer = fixer

    @property
    def fixer(self) -> CodeFixer:
        self._fixer = self._fixer or CodeFixer()
        return self._fixer

    def run(self, data: dict, ctx: FlowContext) -> dict:
        key = data["key"]
        components, _, placements = PageParts.of(data, key)
        contract = assembler.page_contract(key, [c["name"] for c in components])
        errors = [f"In the browser: {e}" for e in data["feedback"]]
        messages = RepairCodePrompt().messages({"code": data["page_code"], "errors": errors, "contract": contract})
        draft = ctx.invoke(data, "code.repair", messages).output
        code, remaining = self.fixer.fix(
            ctx, data, draft, contract=contract, required=[assembler.page_component(key)],
            components=PageParts.component_names(data), asset_ids=PageParts.asset_ids(data),
        )  # fmt: skip
        if remaining:
            warnings = ctx.warn(f"The {key} page uses the standard layout after a failed repair")
            return {"page_code": {key: assembler.template_page(key, placements)}, "warnings": warnings}
        return {"page_code": {key: code}}


class RepairComponentNode(Node):
    name = "repair_component"

    def __init__(self, fixer: CodeFixer | None = None):
        self._fixer = fixer

    @property
    def fixer(self) -> CodeFixer:
        self._fixer = self._fixer or CodeFixer()
        return self._fixer

    def run(self, data: dict, ctx: FlowContext) -> dict:
        component = data["item"]
        name = component["component_name"]
        contract = assembler.component_contract(name)
        errors = [f"In the browser: {e}" for e in data["feedback"]]
        messages = RepairCodePrompt().messages({"code": component["tsx"], "errors": errors, "contract": contract})
        draft = ctx.invoke(data, "code.repair", messages).output
        code, remaining = self.fixer.fix(ctx, data, draft, contract=contract, required=[name])
        if remaining:
            warnings = ctx.warn(f'Dropped the interactive "{data["key"]}" after a failed repair')
            return {"interactives": {data["key"]: None}, "warnings": warnings}
        return {"interactives": {data["key"]: component | {"tsx": code}}}


class PersistLessonNode(Node):
    """The end of the flow: the lesson is ready to show."""

    name = "persist_lesson"
    stage = Stage.GENERATING_LESSON

    def run(self, state: dict, ctx: FlowContext) -> dict:
        lesson_id = state["lesson_id"]
        MediaAssets.persist(lesson_id, state.get("media") or {})
        MediaAsset.objects.filter(lesson_id=lesson_id).exclude(id__in=PageParts.asset_ids(state)).delete()
        lesson = Lesson.objects.get(pk=lesson_id)
        parts = {
            "pages": {k: state["page_code"][k] for k in PAGE_KEYS},
            "interactives": PageParts.component_code(state),
        }
        lesson.advance_to(
            Stage.READY,
            pages=state["pages"],
            final_test=state["final_test"],
            code=state["document_code"],
            code_parts=parts,
            code_version=lesson.code_version + 1,
            warnings=list(dict.fromkeys(state.get("warnings") or [])),
        )
        return {}

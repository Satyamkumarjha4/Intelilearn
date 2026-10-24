"""Stage C: build and verify the lesson document.

Send ×3 compile_page (page.compile → code_fix_loop) → assemble_document → render_check (headless Chromium)
→ persist_lesson, or Send repair_page / repair_component for what broke, then assemble again. If repairs run
out, the broken pages fall back to a template page (and broken components are dropped), with a warning.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from lessons.document import lesson_data
from lessons.models import Lesson, MediaAsset, Stage

from .. import codegen, prompts
from ..context import FlowContext, emit, llm, node_settings, warn
from ..schemas import PAGE_KEYS, component_name
from .author import _store_media, branch
from .common import update_lesson

# --- code_fix_loop subgraph: sanitize → static_check → (repair_code → sanitize …) ------------------------------


class FixState(TypedDict, total=False):
    code: str
    contract: str
    required: list[str]
    components: list[str]
    asset_ids: list[str]
    errors: list[str]
    attempts: int
    max_attempts: int
    data: dict  # lesson context for the gateway (snapshot, lesson_id)
    ok: bool


def _sanitize(state: FixState):
    return {"code": codegen.sanitize(state["code"])}


def _static_check(state: FixState, runtime: Runtime[FlowContext]):
    check = runtime.context.sandbox.check_code(
        state["code"], required=state["required"], components=state.get("components", []),
        asset_ids=state.get("asset_ids", []),
    )  # fmt: skip
    return {"errors": check.errors, "ok": check.ok and not check.errors}


def _after_check(state: FixState) -> str:
    if state["ok"]:
        return END
    return "repair_code" if state.get("attempts", 0) < state["max_attempts"] else END


def _repair_code(state: FixState, runtime: Runtime[FlowContext]):
    emit({"type": "attempt", "node": "code_fix_loop", "attempt": state.get("attempts", 0) + 1,
          "reason": state["errors"][0]})  # fmt: skip
    messages = prompts.repair_code(state["code"], state["errors"], state["contract"])
    code = llm(runtime, state["data"], "code.repair", messages).output
    return {"code": code, "attempts": state.get("attempts", 0) + 1}


def build_fix_loop():
    graph = StateGraph(FixState, context_schema=FlowContext)
    graph.add_node("sanitize", _sanitize)
    graph.add_node("static_check", _static_check)
    graph.add_node("repair_code", _repair_code)
    graph.add_edge(START, "sanitize")
    graph.add_edge("sanitize", "static_check")
    graph.add_conditional_edges("static_check", _after_check, ["repair_code", END])
    graph.add_edge("repair_code", "sanitize")
    return graph.compile()


FIX_LOOP = build_fix_loop()


def code_fix_loop(runtime, data: dict, code: str, *, contract: str, required: list[str], components=(),
                  asset_ids=()) -> tuple[str, list[str]]:  # fmt: skip
    """→ (code, remaining errors). Empty errors means the code passed the static and security check."""
    result = FIX_LOOP.invoke(
        {
            "code": code,
            "contract": contract,
            "required": required,
            "components": list(components),
            "asset_ids": list(asset_ids),
            "attempts": 0,
            "data": data,
            "max_attempts": node_settings(data, "code.repair")["max_attempts"],
        },  # fmt: skip
        context=runtime.context,
    )
    return result["code"], ([] if result["ok"] else result["errors"])


# --- compile pages (parallel) ------------------------------------------------------------------------------------


def _page_parts(data: dict, key: str) -> tuple[list[dict], list[dict], dict]:
    """Components and figures on a page, and the template placements."""
    specs = (data.get("interactive_plan") or {}).get("specs", [])
    interactives = data.get("interactives") or {}
    media = data.get("media") or {}
    components = [{"name": component_name(s["id"]), "anchor": s["anchor_section"], "purpose": s["purpose"]}
                  for s in specs if s["page"] == key and s["id"] in interactives and s["id"] not in media]  # fmt: skip
    figures = [{"asset": media[s["id"]]["asset_id"], "anchor": s["anchor_section"],
                "caption": media[s["id"]]["caption"]}
               for s in specs if s["page"] == key and s["id"] in media]  # fmt: skip
    placements = codegen.placements_for(key, specs, set(interactives) - set(media), media)
    return components, figures, placements


def build_sends(state) -> list[Send]:
    shared = branch(state, interactives=state.get("interactives") or {})
    return [Send("compile_page", shared | {"key": key}) for key in PAGE_KEYS]


def _all_component_names(data) -> list[str]:
    return [component_name(spec_id) for spec_id in (data.get("interactives") or {})]


def _asset_ids(data) -> list[str]:
    return [ref["asset_id"] for ref in (data.get("media") or {}).values()]


def compile_page(data, runtime: Runtime[FlowContext]):
    key = data["key"]
    update_lesson(data["lesson_id"], stage=Stage.GENERATING_LESSON)
    components, figures, placements = _page_parts(data, key)
    names = [c["name"] for c in components]
    draft = llm(runtime, data, "page.compile", prompts.compile_page(data, key, components, figures)).output
    code, errors = code_fix_loop(
        runtime, data, draft, contract=codegen.page_contract(key, names), required=[codegen.page_component(key)],
        components=_all_component_names(data), asset_ids=_asset_ids(data),
    )  # fmt: skip
    if errors:
        warnings = warn(f"The {key} page uses the standard layout: generated code kept failing ({errors[0]})")
        return {"page_code": {key: codegen.template_page(key, placements)}, "warnings": warnings}
    return {"page_code": {key: code}}


# --- assemble, render check, repairs ----------------------------------------------------------------------------


def _components(state) -> dict[str, str]:
    media = state.get("media") or {}
    return {component_name(spec_id): c["tsx"] for spec_id, c in (state.get("interactives") or {}).items()
            if spec_id not in media}  # fmt: skip


def assemble_document(state, runtime: Runtime[FlowContext]):
    pages = dict(state.get("page_code") or {}) | {"test": codegen.test_page()}
    document = codegen.assemble(_components(state), pages)
    check = runtime.context.sandbox.check_code(document, required=["LessonDocument"], asset_ids=_asset_ids(state))
    if check.errors:
        # Each part passed on its own, so this is a clash between parts: fall back to template pages once.
        specs = (state.get("interactive_plan") or {}).get("specs", [])
        built = set(state.get("interactives") or {})
        pages |= {key: codegen.template_page(key, codegen.placements_for(key, specs, built, state.get("media") or {}))
                  for key in PAGE_KEYS}  # fmt: skip
        document = codegen.assemble(_components(state), pages)
        check = runtime.context.sandbox.check_code(document, required=["LessonDocument"], asset_ids=_asset_ids(state))
        if check.errors:
            return {"error": f"The lesson document does not pass the code checks: {check.errors[0]}",
                    "failed_node": "assemble_document", "retry_keys": ["render"], "document_code": None}  # fmt: skip
        return {"document_code": document, "page_code": {k: pages[k] for k in PAGE_KEYS},
                "warnings": warn("Pages use the standard layout: the generated pages clashed")}  # fmt: skip
    return {"document_code": document}


def route_assembled(state) -> str:
    return "render_check" if state.get("document_code") else "mark_failed"


def _media_files(state) -> dict[str, str]:
    from pathlib import Path

    from django.conf import settings

    root = Path(settings.MEDIA_ROOT)
    return {ref["asset_id"]: str(root / ref["file"]) for ref in (state.get("media") or {}).values()}


def _fallback(state, report) -> dict:
    """Out of repairs: standard layout for the broken pages (and pages holding a broken component, which is
    dropped). The document is then assembled and checked once more."""
    specs = (state.get("interactive_plan") or {}).get("specs", [])
    dropped = [s["id"] for s in specs if component_name(s["id"]) in report.components]
    broken = {key for key, errors in report.pages.items() if errors} | {s["page"] for s in specs if s["id"] in dropped}
    if not broken:
        broken = set(PAGE_KEYS)  # a failure we couldn't place: use the standard layout everywhere
    built = set(state.get("interactives") or {}) - set(dropped)
    media = state.get("media") or {}
    pages = {
        key: codegen.template_page(key, codegen.placements_for(key, specs, built, media)) for key in sorted(broken)
    }
    note = f"Sandbox check: standard layout for {', '.join(sorted(broken))}"
    return {"page_code": pages, "interactives": dict.fromkeys(dropped),
            "warnings": warn(note + (f"; dropped {', '.join(dropped)}" if dropped else ""))}  # fmt: skip


def render_check(state, runtime: Runtime[FlowContext]):
    data = lesson_data(state, media_url=lambda asset_id: f"https://media.invalid/{asset_id}")
    report = runtime.context.sandbox.render_check(
        state["document_code"], data, pages=[*PAGE_KEYS, "test"], media_files=_media_files(state)
    )
    rounds = (state.get("attempts") or {}).get("render", 0) + 1
    result = report.as_dict() | {"round": rounds}
    update: dict = {"render_report": result, "attempts": {"render": 1}}
    if report.ok:
        result["decision"] = "pass"
        return update
    problems = [f"{k}: {e[0]}" for k, e in {**report.pages, **report.components}.items() if e] + report.security
    emit({"type": "attempt", "node": "render_check", "attempt": rounds + 1, "reason": problems[0] if problems else ""})
    names = {component_name(spec_id) for spec_id in state.get("interactives") or {}}
    repairable = any(e for k, e in report.pages.items() if k in PAGE_KEYS) or any(
        e for name, e in report.components.items() if name in names
    )
    limit = state["settings"].get("render_check_max_rounds", 2)
    if rounds <= limit and repairable:
        result["decision"] = "repair"
    elif rounds <= limit + 1:
        result["decision"] = "fallback"
        update |= _fallback(state, report)
    else:
        result["decision"] = "fail"
        update |= {"error": "The lesson failed the sandbox render check: " + "; ".join(problems[:3]),
                   "failed_node": "assemble_document", "retry_keys": ["render"]}  # fmt: skip
    return update


def route_render(state):
    report = state["render_report"]
    decision = report["decision"]
    if decision == "pass":
        return "persist_lesson"
    if decision == "fallback":
        return "assemble_document"
    if decision == "fail":
        return "mark_failed"
    names = {component_name(spec_id): spec_id for spec_id in state.get("interactives") or {}}
    sends = [Send("repair_page", branch(state, key=key, feedback=errors, interactives=state.get("interactives"),
                                       page_code=state["page_code"][key]))
             for key, errors in report["pages"].items() if errors and key in PAGE_KEYS]  # fmt: skip
    sends += [Send("repair_component", branch(state, key=names[name], feedback=errors,
                                              item=state["interactives"][names[name]]))
              for name, errors in report["components"].items() if errors and name in names]  # fmt: skip
    return sends


def repair_page(data, runtime: Runtime[FlowContext]):
    key = data["key"]
    components, _, placements = _page_parts(data, key)
    contract = codegen.page_contract(key, [c["name"] for c in components])
    messages = prompts.repair_code(data["page_code"], [f"In the browser: {e}" for e in data["feedback"]], contract)
    draft = llm(runtime, data, "code.repair", messages).output
    code, errors = code_fix_loop(runtime, data, draft, contract=contract, required=[codegen.page_component(key)],
                                 components=_all_component_names(data), asset_ids=_asset_ids(data))  # fmt: skip
    if errors:
        return {"page_code": {key: codegen.template_page(key, placements)},
                "warnings": warn(f"The {key} page uses the standard layout after a failed repair")}  # fmt: skip
    return {"page_code": {key: code}}


def repair_component(data, runtime: Runtime[FlowContext]):
    component = data["item"]
    name = component["component_name"]
    contract = codegen.component_contract(name)
    messages = prompts.repair_code(component["tsx"], [f"In the browser: {e}" for e in data["feedback"]], contract)
    draft = llm(runtime, data, "code.repair", messages).output
    code, errors = code_fix_loop(runtime, data, draft, contract=contract, required=[name])
    if errors:
        return {"interactives": {data["key"]: None}, "warnings": warn(f'Dropped the interactive "{data["key"]}" '
                                                                       "after a failed repair")}  # fmt: skip
    return {"interactives": {data["key"]: component | {"tsx": code}}}


def persist_lesson(state, runtime: Runtime[FlowContext]):
    _store_media(state)
    MediaAsset.objects.filter(lesson_id=state["lesson_id"]).exclude(
        id__in=_asset_ids(state)
    ).delete()  # replaced by a review fix
    lesson = Lesson.objects.get(pk=state["lesson_id"])
    parts = {"pages": {k: state["page_code"][k] for k in PAGE_KEYS}, "interactives": _components(state)}
    update_lesson(
        state["lesson_id"],
        stage=Stage.READY,
        error="",
        pages=state["pages"],
        final_test=state["final_test"],
        code=state["document_code"],
        code_parts=parts,
        code_version=lesson.code_version + 1,
        warnings=list(dict.fromkeys(state.get("warnings") or [])),
    )
    return {}

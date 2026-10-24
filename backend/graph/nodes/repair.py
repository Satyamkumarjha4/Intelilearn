"""runtime_repair graph: the learner's browser hit an error the sandbox check missed.

load_repair → runtime_repair (runtime.repair → code_fix_loop) → verify_repair (assemble, render check,
regression check) → save_version. Any failure raises, so the run fails and the learner can rebuild or roll back.
"""

import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from lessons.document import lesson_data, lesson_source
from lessons.models import Lesson, LessonVersion

from .. import codegen, prompts
from ..context import FlowContext, llm
from ..schemas import PAGE_KEYS
from .build import _media_files, code_fix_loop


class RepairFailed(RuntimeError):
    pass


class RepairState(TypedDict, total=False):
    lesson_id: str
    code_version: int
    error: dict  # {message, stack?, page?, component?}
    snapshot: dict
    settings: dict
    target: dict  # {"kind": "page"|"component", "key"/"name": …}
    parts: dict  # code_parts after the repair
    document: str


def load_repair(state: RepairState, runtime: Runtime[FlowContext]):
    lesson = Lesson.objects.get(pk=state["lesson_id"])
    if lesson.code_version != state["code_version"]:
        raise RepairFailed("The lesson changed since the error was reported; reload it.")
    error = state["error"]
    parts = lesson.code_parts or {}
    component = error.get("component")
    if component and component in parts.get("interactives", {}):
        target = {"kind": "component", "name": component}
    else:
        page = error.get("page") if error.get("page") in PAGE_KEYS else None
        if page is None:  # guess from the stack: which page or component function appears in it
            stack = error.get("stack") or ""
            page = next((key for key in PAGE_KEYS if f"Page_{key}" in stack), "core")
        target = {"kind": "page", "key": page}
    return {"snapshot": lesson.config_snapshot, "settings": lesson.settings_snapshot, "target": target,
            "parts": parts}  # fmt: skip


def _references(code: str) -> set[str]:
    return set(re.findall(r"<(Interactive_\w+)", code)) | set(re.findall(r'asset=\{?"([^"]+)"', code))


def runtime_repair(state: RepairState, runtime: Runtime[FlowContext]):
    parts = {
        "pages": dict(state["parts"].get("pages", {})),
        "interactives": dict(state["parts"].get("interactives", {})),
    }
    target = state["target"]
    if target["kind"] == "component":
        name = target["name"]
        code, contract, required = parts["interactives"][name], codegen.component_contract(name), [name]
    else:
        key = target["key"]
        code, required = parts["pages"][key], [codegen.page_component(key)]
        contract = codegen.page_contract(key, sorted(set(re.findall(r"<(Interactive_\w+)", code))))
    draft = llm(runtime, state, "runtime.repair", prompts.runtime_repair(code, state["error"], contract)).output
    fixed, errors = code_fix_loop(runtime, state, draft, contract=contract, required=required,
                                  components=list(parts["interactives"]))  # fmt: skip
    if errors:
        raise RepairFailed(f"The repaired code still fails the checks: {errors[0]}")
    if not _references(code) <= _references(fixed):
        raise RepairFailed("The repair removed interactives or figures; it was rejected.")
    if target["kind"] == "component":
        parts["interactives"][target["name"]] = fixed
    else:
        parts["pages"][target["key"]] = fixed
    return {"parts": parts}


def verify_repair(state: RepairState, runtime: Runtime[FlowContext]):
    lesson = Lesson.objects.get(pk=state["lesson_id"])
    parts = state["parts"]
    document = codegen.assemble(parts["interactives"], parts["pages"] | {"test": codegen.test_page()})
    source = lesson_source(lesson)
    report = runtime.context.sandbox.render_check(
        document, lesson_data(source, media_url=lambda asset_id: f"https://media.invalid/{asset_id}"),
        pages=[*PAGE_KEYS, "test"], media_files=_media_files(source),
    )  # fmt: skip
    if not report.ok:
        problems = [f"{k}: {e[0]}" for k, e in {**report.pages, **report.components}.items() if e]
        raise RepairFailed("The repaired lesson still fails the sandbox check: " + "; ".join(problems[:2]))
    return {"document": document}


def save_version(state: RepairState, runtime: Runtime[FlowContext]):
    lesson = Lesson.objects.get(pk=state["lesson_id"])
    LessonVersion.objects.create(
        lesson=lesson, code_version=lesson.code_version, code=lesson.code, code_parts=lesson.code_parts,
        reason=f"Before runtime repair: {state['error'].get('message', '')}"[:300],
    )  # fmt: skip
    lesson.code, lesson.code_parts = state["document"], state["parts"]
    lesson.code_version += 1
    lesson.runtime_repairs += 1
    lesson.save(update_fields=["code", "code_parts", "code_version", "runtime_repairs", "updated_at"])
    return {}


def build_runtime_repair_graph(checkpointer=None):
    graph = StateGraph(RepairState, context_schema=FlowContext)
    for name, fn in [("load_repair", load_repair), ("runtime_repair", runtime_repair),
                     ("verify_repair", verify_repair), ("save_version", save_version)]:  # fmt: skip
        graph.add_node(name, fn)
    graph.add_edge(START, "load_repair")
    graph.add_edge("load_repair", "runtime_repair")
    graph.add_edge("runtime_repair", "verify_repair")
    graph.add_edge("verify_repair", "save_version")
    graph.add_edge("save_version", END)
    return graph.compile(checkpointer=checkpointer)

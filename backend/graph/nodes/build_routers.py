"""Stage C's conditional edges."""

from langgraph.types import Send

from ..schemas import PAGE_KEYS, component_name
from .branches import BranchBuilder
from .routers import Router


class BuildRouter(Router):
    """After prepare_build: compile the three content pages in parallel."""

    def __call__(self, state: dict):
        shared = {"interactives": state.get("interactives") or {}}
        return [Send("compile_page", BranchBuilder.of(state, key=key, **shared)) for key in PAGE_KEYS]


class AssembledRouter(Router):
    def __call__(self, state: dict) -> str:
        return "render_check" if state.get("document_code") else "mark_failed"


class RenderRouter(Router):
    """After the render check: persist, fall back to the template layout, fail, or repair only what broke."""

    def __call__(self, state: dict):
        report = state["render_report"]
        decision = report["decision"]
        if decision == "pass":
            return "persist_lesson"
        if decision == "fallback":
            return "assemble_document"
        if decision == "fail":
            return "mark_failed"
        interactives = state.get("interactives") or {}
        names = {component_name(spec_id): spec_id for spec_id in interactives}
        sends = [
            Send(
                "repair_page",
                BranchBuilder.of(
                    state, key=key, feedback=errors, interactives=interactives, page_code=state["page_code"][key]
                ),
            )
            for key, errors in report["pages"].items()
            if errors and key in PAGE_KEYS
        ]
        sends += [
            Send(
                "repair_component",
                BranchBuilder.of(state, key=names[name], feedback=errors, item=interactives[names[name]]),
            )
            for name, errors in report["components"].items()
            if errors and name in names
        ]
        return sends

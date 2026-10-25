"""The deterministic decisions of Stage C: what goes on each page, and what to do with a render-check report."""

from dataclasses import dataclass, field
from typing import Literal

from .codegen import DocumentAssembler
from .schemas import PAGE_KEYS, component_name

assembler = DocumentAssembler()
Decision = Literal["pass", "repair", "fallback", "fail"]


class PageParts:
    """The interactives and figures that belong on one page, and where the template places them."""

    @staticmethod
    def of(data: dict, key: str) -> tuple[list[dict], list[dict], dict[str, list[str]]]:
        """→ (components, figures, placements) for page `key`."""
        specs = (data.get("interactive_plan") or {}).get("specs", [])
        interactives = data.get("interactives") or {}
        media = data.get("media") or {}
        components = [
            {"name": component_name(s["id"]), "anchor": s["anchor_section"], "purpose": s["purpose"]}
            for s in specs
            if s["page"] == key and s["id"] in interactives and s["id"] not in media
        ]
        figures = [
            {"asset": media[s["id"]]["asset_id"], "anchor": s["anchor_section"], "caption": media[s["id"]]["caption"]}
            for s in specs
            if s["page"] == key and s["id"] in media
        ]
        placements = assembler.placements_for(key, specs, set(interactives) - set(media), media)
        return components, figures, placements

    @staticmethod
    def component_code(state: dict) -> dict[str, str]:
        """Component name → its checked code, for the interactives that are code (not media)."""
        media = state.get("media") or {}
        return {
            component_name(spec_id): c["tsx"]
            for spec_id, c in (state.get("interactives") or {}).items()
            if spec_id not in media
        }

    @staticmethod
    def asset_ids(state: dict) -> list[str]:
        return [ref["asset_id"] for ref in (state.get("media") or {}).values()]

    @staticmethod
    def component_names(state: dict) -> list[str]:
        return [component_name(spec_id) for spec_id in (state.get("interactives") or {})]


@dataclass(frozen=True)
class RenderVerdict:
    decision: Decision
    report: dict  # the report with `round` and `decision` filled in
    problems: list[str] = field(default_factory=list)  # one line per broken page or component, for the message
    update: dict = field(default_factory=dict)  # state changes of a fallback


class RenderPolicy:
    """pass → persist; broken pages or interactives and rounds left → repair only those; rounds spent → the standard
    (template) layout for the broken pages, dropping a broken interactive, checked once more; still broken → fail."""

    def decide(self, report, *, state: dict, round_number: int) -> RenderVerdict:
        data = report.as_dict() | {"round": round_number}
        if report.ok:
            return RenderVerdict("pass", data | {"decision": "pass"})
        problems = report.problems()
        names = set(PageParts.component_names(state))
        repairable = any(report.pages.get(key) for key in PAGE_KEYS) or any(
            errors for name, errors in report.components.items() if name in names
        )
        limit = state["settings"].get("render_check_max_rounds", 2)
        if round_number <= limit and repairable:
            return RenderVerdict("repair", data | {"decision": "repair"}, problems)
        if round_number <= limit + 1:
            return RenderVerdict("fallback", data | {"decision": "fallback"}, problems, self.fallback(state, report))
        return RenderVerdict("fail", data | {"decision": "fail"}, problems)

    def fallback(self, state: dict, report) -> dict:
        """Standard layout for the broken pages (and for the pages holding a broken interactive, which is dropped)."""
        specs = (state.get("interactive_plan") or {}).get("specs", [])
        dropped = [s["id"] for s in specs if component_name(s["id"]) in report.components]
        broken = {key for key, errors in report.pages.items() if errors and key in PAGE_KEYS}
        broken |= {s["page"] for s in specs if s["id"] in dropped}
        if not broken:
            broken = set(PAGE_KEYS)  # a failure we could not place: the standard layout everywhere
        built = set(state.get("interactives") or {}) - set(dropped)
        media = state.get("media") or {}
        pages = {
            key: assembler.template_page(key, assembler.placements_for(key, specs, built, media))
            for key in sorted(broken)
        }
        note = f"Sandbox check: standard layout for {', '.join(sorted(broken))}"
        if dropped:
            note += f"; dropped {', '.join(dropped)}"
        return {"page_code": pages, "interactives": dict.fromkeys(dropped), "_warning": note}

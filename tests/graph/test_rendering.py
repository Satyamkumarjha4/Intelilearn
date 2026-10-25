"""Unit under test: `graph.rendering` (`PageParts`, `RenderPolicy`): what belongs on each page of the document, and what
to do with a render-check report.

Why: the render check is the last gate before a learner sees code. The policy decides whether a broken lesson is
repaired page by page, falls back to the standard layout, or fails, and a mistake loops forever, throws away a working
page, or ships a broken one. The page parts decide where each interactive and figure goes.

Use cases:
- page parts: components and figures for one page only, a figure winning over a component for the same spec,
  the placements for the template, and the component code of the interactives that are code
- a clean report passes
- broken pages or interactives with rounds left are repaired; the problems name them
- a failure that cannot be placed (only security violations, or an unknown component) is not repairable
- once repair rounds are spent the broken pages (and pages with a broken interactive) fall back to the standard layout
  and the broken interactive is dropped; with nothing identifiable, every page falls back
- after the fallback round a still-broken lesson fails
- the number of repair rounds comes from the lesson's settings
"""

import pytest
from support.lesson_data import make_interactive_plan, make_state

from graph.rendering import PageParts, RenderPolicy
from graph.sandbox import RenderReport

policy = RenderPolicy()
BUILT = {
    "widget_core": {"spec_id": "widget_core", "component_name": "Interactive_widget_core", "tsx": "function A() {}"},
    "widget_advanced": {"spec_id": "widget_advanced", "component_name": "Interactive_widget_advanced", "tsx": "B"},
}


def state(**extra):
    plan = make_interactive_plan()
    plan["specs"][0] |= {"kind": "image", "media_query": "q"}
    media = {"widget_introduction": {"asset_id": "a-1", "caption": "Amoeba"}}
    return make_state(**({"interactive_plan": plan, "interactives": dict(BUILT), "media": media} | extra))


class TestPageParts:
    def test_components_and_figures_are_the_ones_on_that_page(self):
        components, figures, placements = PageParts.of(state(), "core")

        assert components == [
            {
                "name": "Interactive_widget_core",
                "anchor": "s1",
                "purpose": "Shows the main idea of the core page better than text.",
            }
        ]
        assert figures == [] and placements == {"s1": ["<Interactive_widget_core />"]}

    def test_a_figure_is_a_figure_not_a_component(self):
        components, figures, placements = PageParts.of(state(), "introduction")

        assert components == [] and placements == {"s1": ['<Figure asset="a-1" />']}
        assert figures == [{"asset": "a-1", "anchor": "s1", "caption": "Amoeba"}]

    def test_unbuilt_specs_are_left_out(self):
        built = {k: v for k, v in BUILT.items() if k != "widget_advanced"}

        assert PageParts.of(state(interactives=built), "advanced") == ([], [], {})

    def test_component_code_is_for_interactives_that_are_code_not_media(self):
        both = BUILT | {"widget_introduction": {"tsx": "image fallback"}}

        assert PageParts.component_code(state(interactives=both)) == {
            "Interactive_widget_core": "function A() {}", "Interactive_widget_advanced": "B",
        }  # fmt: skip

    def test_asset_ids_and_component_names(self):
        assert PageParts.asset_ids(state()) == ["a-1"]
        assert PageParts.component_names(state()) == ["Interactive_widget_core", "Interactive_widget_advanced"]


def report(pages=None, components=None, security=()):
    pages = {"introduction": [], "core": [], "advanced": []} | (pages or {})
    ok = not (any(pages.values()) or any((components or {}).values()) or security)
    return RenderReport(ok=ok, pages=pages, components=components or {}, security=list(security))


def decide(rep, round_number=1, **settings):
    return policy.decide(
        rep, state=state(settings={"render_check_max_rounds": 2} | settings), round_number=round_number
    )


def test_a_clean_report_passes():
    verdict = decide(report())

    assert verdict.decision == "pass" and verdict.report["decision"] == "pass" and verdict.report["round"] == 1


def test_broken_pages_and_interactives_with_rounds_left_are_repaired_and_named():
    verdict = decide(report({"core": ["Runtime error: x is undefined"]}, {"Interactive_widget_core": ["boom"]}))

    assert verdict.decision == "repair"
    assert verdict.problems == ["core: Runtime error: x is undefined", "Interactive_widget_core: boom"]


def test_a_failure_on_a_page_that_is_not_a_content_page_cannot_be_repaired_by_a_model():
    verdict = decide(report({"test": ["Runtime error"]}), round_number=1)

    assert verdict.decision == "fallback"  # not repairable: only the three content pages are written by a model


@pytest.mark.parametrize(
    "rep",
    [
        report(security=["Blocked request: GET https://evil.example"]),
        report(components={"Interactive_unknown": ["boom"]}),
    ],
    ids=["security-only", "unknown-component"],
)
def test_a_failure_that_cannot_be_placed_is_not_repairable(rep):
    assert decide(rep).decision == "fallback"


def test_once_repair_rounds_are_spent_broken_pages_fall_back_to_the_standard_layout():
    verdict = decide(report({"core": ["boom"]}), round_number=3)

    assert verdict.decision == "fallback"
    assert (
        list(verdict.update["page_code"]) == ["core"] and "function Page_core()" in verdict.update["page_code"]["core"]
    )
    assert (
        verdict.update["interactives"] == {} and verdict.update["_warning"] == "Sandbox check: standard layout for core"
    )


def test_a_broken_interactive_is_dropped_and_its_page_falls_back_without_it():
    verdict = decide(report(components={"Interactive_widget_core": ["boom"]}), round_number=3)

    assert verdict.update["interactives"] == {"widget_core": None}
    assert "Interactive_widget_core" not in verdict.update["page_code"]["core"]
    assert verdict.update["_warning"] == "Sandbox check: standard layout for core; dropped widget_core"


def test_with_nothing_identifiable_every_page_falls_back():
    verdict = decide(report(security=["Blocked request"]), round_number=3)

    assert sorted(verdict.update["page_code"]) == ["advanced", "core", "introduction"]
    assert 'Figure asset="a-1"' in verdict.update["page_code"]["introduction"]


def test_after_the_fallback_round_a_still_broken_lesson_fails():
    verdict = decide(report({"core": ["still broken"]}), round_number=4)

    assert verdict.decision == "fail" and verdict.problems == ["core: still broken"] and verdict.update == {}


def test_the_number_of_repair_rounds_comes_from_the_settings():
    assert decide(report({"core": ["x"]}), round_number=2, render_check_max_rounds=1).decision == "fallback"
    assert decide(report({"core": ["x"]}), round_number=2, render_check_max_rounds=3).decision == "repair"

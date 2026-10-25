"""Unit under test: `graph.codegen.DocumentAssembler`, which builds the lesson document (template pages, the test page,
and the assembly of components and pages into one TSX file).

Why: it is the deterministic fallback for everything a model gets wrong, and the page-4 test is never left to a model.
If a template page failed to compile, or the assembled document failed the sandbox check, the learner would get no
lesson at all. The tests build documents and run them through the real sandbox check.

Use cases:
- a template page renders every section through <Section>, with interactives and figures placed after their anchor
- a template page without placements still renders its sections
- the test page renders the Assessment from the injected test
- placements put a built interactive or a stored figure after its anchor; unbuilt specs and other pages are skipped
- an assembled document wraps each interactive in an error boundary, declares the four pages in order, ends with render
- an assembled document passes the real sandbox check (the template pages, the test page and wrapped components)
- the contracts name the component to declare and the components a page may use
"""

import pytest
from support.lesson_data import make_interactive_plan

from graph.codegen import DocumentAssembler
from graph.sandbox import SandboxRunner

assembler = DocumentAssembler()
COMPONENT = "function Interactive_widget_core() {\n  return <div>hi</div>;\n}\n"
needs_sandbox = pytest.mark.skipif(not SandboxRunner().available(), reason="the sandbox package is not installed")


def full_pages(placements=None):
    pages = {
        key: assembler.template_page(key, (placements or {}).get(key, {}))
        for key in ("introduction", "core", "advanced")
    }
    return pages | {"test": assembler.test_page()}


def test_a_template_page_renders_every_section_with_placements_after_their_anchor():
    code = assembler.template_page("core", {"s1": ["<Interactive_widget_core />"], "s2": ['<Figure asset="a1" />']})

    assert "function Page_core()" in code and "LESSON.pages.core" in code
    assert '{section.id === "s1" ? (<><Interactive_widget_core /></>) : null}' in code
    assert '{section.id === "s2" ? (<><Figure asset="a1" /></>) : null}' in code
    assert '<KeyPoints title="Summary"' in code


def test_a_template_page_without_placements_still_renders_its_sections():
    code = assembler.template_page("introduction", {})

    assert "{null}" in code and "<Section key={section.id} section={section}>" in code


def test_the_test_page_renders_the_assessment_from_the_injected_test():
    code = assembler.test_page()

    assert "function Page_test()" in code and "<Assessment test={LESSON.final_test} />" in code


class TestPlacements:
    def specs(self):
        return make_interactive_plan()["specs"]

    def test_places_built_interactives_and_stored_figures_after_their_anchor(self):
        specs = self.specs()

        placed = assembler.placements_for("core", specs, {"widget_core"}, {})
        with_figure = assembler.placements_for(
            "introduction", specs, set(), {"widget_introduction": {"asset_id": "a-1"}}
        )

        assert placed == {"s1": ["<Interactive_widget_core />"]}
        assert with_figure == {"s1": ['<Figure asset="a-1" />']}

    def test_skips_what_was_not_built_and_other_pages(self):
        assert assembler.placements_for("advanced", self.specs(), {"widget_core"}, {}) == {}

    def test_a_figure_wins_over_a_component_for_the_same_spec(self):
        placed = assembler.placements_for("core", self.specs(), {"widget_core"}, {"widget_core": {"asset_id": "x"}})

        assert placed == {"s1": ['<Figure asset="x" />']}


class TestAssemble:
    def test_wraps_each_interactive_in_a_boundary_and_declares_the_pages_in_order(self):
        document = assembler.assemble({"Interactive_widget_core": COMPONENT}, full_pages())

        assert 'const Interactive_widget_core = withBoundary("Interactive_widget_core", (() => {' in document
        assert "  return Interactive_widget_core;\n})());" in document
        order = [document.index(f"function Page_{key}()") for key in assembler.PAGE_ORDER]
        assert order == sorted(order)
        assert document.rstrip().endswith("render(<LessonDocument />);")
        assert '{ key: "test", title: LESSON.final_test.title, render: Page_test }' in document

    def test_components_are_declared_in_name_order_before_the_pages(self):
        document = assembler.assemble({"Interactive_b": COMPONENT, "Interactive_a": COMPONENT}, full_pages())

        assert (
            document.index("const Interactive_a")
            < document.index("const Interactive_b")
            < document.index("function Page_introduction")
        )

    @needs_sandbox
    def test_the_assembled_document_passes_the_real_sandbox_check(self):
        specs = make_interactive_plan()["specs"]
        placements = {
            key: assembler.placements_for(key, specs, {"widget_core"}, {})
            for key in ("introduction", "core", "advanced")
        }
        document = assembler.assemble({"Interactive_widget_core": COMPONENT}, full_pages(placements))

        result = SandboxRunner().check_code(document, required=["LessonDocument"])

        assert result.errors == []

    @needs_sandbox
    def test_a_figure_for_an_unknown_asset_fails_the_check_and_a_known_one_passes(self):
        pages = full_pages({"core": {"s1": ['<Figure asset="a-1" />']}})
        document = assembler.assemble({}, pages)

        unknown = SandboxRunner().check_code(document, required=["LessonDocument"], asset_ids=[])
        known = SandboxRunner().check_code(document, required=["LessonDocument"], asset_ids=["a-1"])

        assert any("[figure-asset]" in e for e in unknown.errors) and known.errors == []


def test_the_contracts_name_what_to_declare_and_what_a_page_may_use():
    assert "function Page_core()" in assembler.page_contract("core", [])
    assert "It may use these already-defined components: Interactive_a, Interactive_b." in assembler.page_contract(
        "core", ["Interactive_a", "Interactive_b"]
    )
    assert "function Interactive_a()" in assembler.component_contract("Interactive_a")

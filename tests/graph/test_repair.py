"""Unit under test: `graph.repair`: `RepairTargetLocator` (which part of the lesson crashed), `CodeSignature` and
`RegressionCheck` (whether a repair lost content).

Why: a runtime repair rewrites code that learners are reading. Sending the model to the wrong part wastes a repair, and
accepting a repair that quietly dropped a section or an interactive is worse than not repairing at all.

Use cases:
- an error that names an interactive that exists is a component target (message first, then stack)
- an error from a page is a page target, by the viewer's `page` or by `Page_x` in the stack
- the test page, an unknown name and an empty error have no target
- a signature lists the interactives and figures a page places, the section ids it names and whether it maps sections
- a repair that keeps everything passes; one that drops an interactive, a figure, a section or the sections loop, or
  changes the set of pages or interactives, is a problem
"""

import pytest

from graph.repair import CodeSignature, RegressionCheck, RepairTarget, RepairTargetLocator

PARTS = {"pages": {"introduction": "i", "core": "c", "advanced": "a"}, "interactives": {"Interactive_widget_core": "w"}}


class TestLocator:
    locate = staticmethod(RepairTargetLocator().locate)

    def test_an_interactive_named_in_the_message_is_the_target(self):
        error = {"message": "Interactive_widget_core crashed: x is undefined", "page": "core"}

        assert self.locate(error, PARTS) == RepairTarget("component", "Interactive_widget_core")

    def test_an_interactive_named_only_in_the_stack_is_the_target(self):
        error = {"message": "x is undefined", "stack": "at Interactive_widget_core (doc:12)\nat Page_core"}

        assert self.locate(error, PARTS) == RepairTarget("component", "Interactive_widget_core")

    def test_an_interactive_the_lesson_does_not_have_is_ignored(self):
        assert self.locate({"message": "Interactive_ghost failed", "page": "core"}, PARTS) == RepairTarget(
            "page", "core"
        )

    def test_the_page_the_viewer_reports_is_the_target(self):
        assert self.locate({"message": "boom", "page": "advanced"}, PARTS) == RepairTarget("page", "advanced")

    def test_a_page_function_in_the_stack_is_the_target(self):
        assert self.locate({"message": "boom", "stack": "at Page_introduction (doc:3)"}, PARTS) == RepairTarget(
            "page", "introduction"
        )

    @pytest.mark.parametrize("error", [{"message": "boom", "page": "test"}, {"message": "boom"}, {}])
    def test_the_test_page_and_unplaceable_errors_have_no_target(self, error):
        assert self.locate(error, PARTS) is None

    def test_a_target_round_trips_through_the_graph_state(self):
        target = RepairTarget("page", "core")

        assert RepairTarget.from_dict(target.as_dict()) == target


class TestSignature:
    def test_it_lists_what_the_page_places_and_names(self):
        code = '<Section><Interactive_a /><Figure asset="f-1" /></Section> {s.id === "s2" && x} page.sections.map(f)'

        assert CodeSignature.of(code, ["s1", "s2"]) == {
            "interactive Interactive_a", "figure f-1", "section s2", "all sections",
        }  # fmt: skip

    def test_plain_code_has_an_empty_signature(self):
        assert CodeSignature.of("function Page_core() { return null; }", ["s1"]) == frozenset()


class TestRegression:
    check = staticmethod(RegressionCheck().problems)
    DATA = {"core": {"sections": [{"id": "s1"}, {"id": "s2"}]}}
    BEFORE = {
        "pages": {"core": 'page.sections.map(s => <Section><Interactive_w />{s.id === "s2" && <Figure asset="f-1" />}'},
        "interactives": {"Interactive_w": "w"},
    }  # fmt: skip

    def test_a_repair_that_keeps_everything_passes(self):
        after = {**self.BEFORE, "pages": {"core": self.BEFORE["pages"]["core"] + " // fixed"}}

        assert self.check(self.BEFORE, after, self.DATA) == []

    @pytest.mark.parametrize(
        ("old", "new", "lost"),
        [
            ("<Interactive_w />", "<div />", "interactive Interactive_w"),
            ('<Figure asset="f-1" />', "<div />", "figure f-1"),
            ('{s.id === "s2"}', "{}", "section s2"),
            ("page.sections.map(f)", "page.sections[0]", None),
        ],
    )
    def test_dropped_content_is_reported(self, old, new, lost):
        before = {"pages": {"core": old}, "interactives": {}}
        after = {"pages": {"core": new}, "interactives": {}}

        problems = self.check(before, after, self.DATA)

        if lost:
            assert problems == [f"The repair dropped content from the core page: {lost}"]
        else:
            assert problems == []  # `.sections` is still read, so the loop is still there

    def test_the_sections_loop_going_away_is_reported(self):
        before = {"pages": {"core": "page.sections.map(f)"}, "interactives": {}}
        after = {"pages": {"core": "<p>hi</p>"}, "interactives": {}}

        assert self.check(before, after, self.DATA) == ["The repair dropped content from the core page: all sections"]

    def test_a_changed_set_of_pages_or_interactives_is_reported(self):
        after = {"pages": {"core": "x"}, "interactives": {"Interactive_new": "n"}}

        problems = self.check({"pages": {"core": "x", "advanced": "y"}, "interactives": {}}, after, self.DATA)

        assert problems == [
            "The repair changed the lesson's pages: advanced",
            "The repair changed the lesson's interactives: Interactive_new",
        ]

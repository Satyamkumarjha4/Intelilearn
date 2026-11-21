"""Unit under test: how the graph keeps what a validator refused: `FlowContext.reject`, the call id an `LLMNode`
leaves in the state (`last_calls`), `ValidateNode` and the writers that check their own output (`ContentWriter`,
`SheetWriter`, the interactive plan).

Why: a refused output is the evidence of whether the model or the validator was wrong, and it is gone the moment the
node asks again. Each place that refuses an output must hand it, with the problems, to the call that wrote it; and a
place that does not refuse must hand over nothing, or staff would read good outputs as bad ones.

Use cases:
- `FlowContext.reject` passes the call id, the output and the problems on, and does nothing without a call id
- an LLM node keeps the id of its call in `last_calls`, under its feedback key; with no call id it adds nothing
- `last_calls` is declared in the flow's state, because the graph drops the keys that are not
- a validating node that refuses an output (a bundle with a problem, on the first attempt and on the last) hands the
  output and the problems to the call that wrote it, and one that accepts hands over nothing
- a node whose state has no call id for its output (a run started before this) still refuses as before
- a page, a widget, a batch of test questions, a sheet and an interactive plan the validator refuses are handed over;
  ones it accepts are not
"""

from typing import get_type_hints

import pytest
from support.lesson_data import make_interactive_plan, make_page, make_state
from support.study_data import make_cheat_sheet

from graph.authoring import ContentWriter
from graph.context import FlowContext
from graph.nodes.author import ValidateInteractivePlanNode
from graph.nodes.diagnose import GenerateDiagnosticNode, ValidateDiagnosticNode
from graph.nodes.sheets import GenerateSheetNode
from graph.questions import Batch, LessonTestBlueprint
from graph.state import FlowState

pytestmark = pytest.mark.django_db


class TestContext:
    def test_reject_passes_everything_on(self, ctx, rejections):
        ctx.reject(7, {"a": 1}, ["bad"])

        assert rejections.rejected == [(7, {"a": 1}, ["bad"])]

    def test_reject_does_nothing_without_a_call_id(self, ctx, rejections):
        ctx.reject(None, {"a": 1}, ["bad"])

        assert rejections.rejected == []

    def test_a_context_made_without_a_sink_has_the_real_one(self, gateway):
        from llm_registry.rejections import RejectedOutputs

        assert isinstance(FlowContext(gateway=gateway).rejections, RejectedOutputs)


class TestLastCalls:
    def test_an_llm_node_keeps_the_id_of_its_call_under_its_feedback_key(
        self, lesson_state, gateway, runtime, valid_bundle
    ):
        gateway.numbering().script("diagnostic.generate", valid_bundle)

        update = GenerateDiagnosticNode()(lesson_state, runtime)

        assert update["last_calls"] == {"diagnostic": 1}

    def test_without_a_call_id_it_adds_nothing(self, lesson_state, gateway, runtime, valid_bundle):
        gateway.script("diagnostic.generate", valid_bundle)

        assert "last_calls" not in GenerateDiagnosticNode()(lesson_state, runtime)

    def test_the_key_is_declared_in_the_flow_state(self):
        assert "last_calls" in get_type_hints(FlowState)


class TestValidateNode:
    def state(self, lesson_state, bundle, **extra):
        return lesson_state | {"bundle": bundle, "last_calls": {"diagnostic": 41}} | extra

    def test_a_refused_bundle_goes_to_the_call_that_wrote_it(self, lesson_state, runtime, rejections, valid_bundle):
        valid_bundle["diagnostic"].pop()
        state = self.state(lesson_state, valid_bundle, attempts={"diagnostic": 1})

        update = ValidateDiagnosticNode()(state, runtime)

        assert rejections.rejected == [(41, valid_bundle, update["feedback"]["diagnostic"])]

    def test_the_last_attempt_is_kept_too(self, lesson_state, runtime, rejections, valid_bundle):
        valid_bundle["diagnostic"].pop()
        state = self.state(lesson_state, valid_bundle, attempts={"diagnostic": 2})

        update = ValidateDiagnosticNode()(state, runtime)

        assert "error" in update and [r[0] for r in rejections.rejected] == [41]

    def test_an_accepted_bundle_hands_over_nothing(self, lesson_state, runtime, rejections, valid_bundle):
        ValidateDiagnosticNode()(self.state(lesson_state, valid_bundle), runtime)

        assert rejections.rejected == []

    def test_a_state_without_a_call_id_still_refuses_as_before(self, lesson_state, runtime, rejections, valid_bundle):
        valid_bundle["diagnostic"].pop()
        state = lesson_state | {"bundle": valid_bundle, "attempts": {"diagnostic": 1}}

        update = ValidateDiagnosticNode()(state, runtime)

        assert update["feedback"]["diagnostic"] and rejections.rejected == []


class TestWriters:
    def test_a_page_the_validator_refuses_is_handed_over(self, ctx, gateway, rejections):
        data = make_state() | {"snapshot": {}}
        page = make_page("core", data["plan"])
        page["sections"][0]["body"] = "Too short."
        gateway.numbering().script("page.generate", page)

        written, problems = ContentWriter(ctx).page(data, "core", None)

        assert problems and rejections.rejected == [(1, written, problems)]

    def test_a_page_the_validator_accepts_is_not(self, ctx, gateway, rejections):
        data = make_state() | {"snapshot": {}}
        gateway.numbering().script("page.generate", make_page("core", data["plan"]))

        _, problems = ContentWriter(ctx).page(data, "core", None)

        assert problems == [] and rejections.rejected == []

    def test_a_widget_the_sandbox_refuses_is_handed_over(self, ctx, gateway, sandbox, rejections):
        data = make_state() | {"snapshot": {}}
        spec = data["interactive_plan"]["specs"][0]
        sandbox.code_errors = ["line 1:0 [forbidden-global] `fetch` is not allowed in lesson code"]
        gateway.numbering().script("interactive.generate", {
            "spec_id": spec["id"], "component_name": "Interactive_x", "tsx": "function Interactive_x(){ fetch('/') }"
        })  # fmt: skip

        _, problems = ContentWriter(ctx).component(data, spec, None)

        assert problems == sandbox.code_errors
        [(call_id, tsx, kept)] = rejections.rejected  # the sanitiser ends the code with a newline
        assert (call_id, tsx.strip(), kept) == (1, "function Interactive_x(){ fetch('/') }", problems)

    def test_a_widget_the_sandbox_accepts_is_not(self, ctx, gateway, rejections):
        data = make_state() | {"snapshot": {}}
        spec = data["interactive_plan"]["specs"][0]
        gateway.numbering().script("interactive.generate", {
            "spec_id": spec["id"], "component_name": "Interactive_x", "tsx": "function Interactive_x(){ return null }"
        })  # fmt: skip

        _, problems = ContentWriter(ctx).component(data, spec, None)

        assert problems == [] and rejections.rejected == []

    def test_the_questions_the_validator_refuses_are_handed_over(self, ctx, gateway, rejections):
        data = make_state() | {"snapshot": {}}
        batch = Batch("b1", tuple(LessonTestBlueprint.for_topic(True).cells[:2]))
        gateway.numbering().script("test.generate", {"questions": []})

        written, problems = ContentWriter(ctx).questions(data, batch, None)

        assert problems and rejections.rejected == [(1, written, problems)]

    def test_a_sheet_the_validator_refuses_is_handed_over(self, lesson_state, gateway, runtime, rejections):
        gateway.numbering().script("study.generate", make_cheat_sheet())
        state = lesson_state | {"key": "cheat_sheet", "concepts": ["Quantum tunnelling", "Dark energy", "Entropy"]}

        update = GenerateSheetNode()(state, runtime)

        problems = update["feedback"]["sheet:cheat_sheet"]
        assert problems and rejections.rejected == [(1, update["sheets"]["cheat_sheet"], problems)]

    def test_a_sheet_the_validator_accepts_is_not(self, lesson_state, gateway, runtime, rejections):
        gateway.numbering().script("study.generate", make_cheat_sheet())

        GenerateSheetNode()(lesson_state | {"key": "cheat_sheet"}, runtime)

        assert rejections.rejected == []

    def test_an_interactive_plan_the_validator_refuses_is_handed_over(self, lesson_state, runtime, rejections):
        full = make_state()
        plan = make_interactive_plan()
        plan["specs"][0]["anchor_section"] = "s99"
        state = lesson_state | {"pages": full["pages"], "interactive_plan": plan, "attempts": {"interactive_plan": 1},
                                "last_calls": {"interactive_plan": 52}}  # fmt: skip

        update = ValidateInteractivePlanNode()(state, runtime)

        assert rejections.rejected == [(52, plan, update["feedback"]["interactive_plan"])]

    def test_an_interactive_plan_the_validator_accepts_is_not(self, lesson_state, runtime, rejections):
        full = make_state()
        state = lesson_state | {"pages": full["pages"], "interactive_plan": full["interactive_plan"],
                                "last_calls": {"interactive_plan": 52}}  # fmt: skip

        ValidateInteractivePlanNode()(state, runtime)

        assert rejections.rejected == []

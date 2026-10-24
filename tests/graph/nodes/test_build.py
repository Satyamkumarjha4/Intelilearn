"""Unit under test: the Stage C nodes in `graph.nodes.build` and `graph.nodes.build_routers`: the code-fix loop,
compiling pages, assembling the document, the render check, repairs, and saving the finished lesson.

Why: this is where generated code meets the sandbox. Every failure here either ships a broken lesson or throws away a
good one: a page that cannot be fixed must fall back to the standard layout, not block the lesson; a repair must see
the browser's errors; a clash between parts must be handled once and then fail loudly; and the lesson must be saved
atomically as ready, with only the media it uses.

Use cases:
- the fix loop: clean code passes without a model call; fences and imports are stripped first; failing code is sent to
  code.repair with the errors and the contract until it passes or attempts run out
- compile_page: the page's code, checked by the loop; when it keeps failing, the standard layout and a warning
- assemble_document: a clean document; a clash between parts falls back to template pages once; a document that still
  fails is an error with the node to resume at
- render_check: sends the public lesson data and the media files; records the policy's decision; a fallback carries its
  state changes and a warning; a failure sets the error
- repair_page: the model is told what happened in the browser; a repair that fails falls back to the template
- repair_component: a repaired component replaces the old; one that fails is dropped with a warning
- persist_lesson: the lesson becomes ready with its code and parts, code_version goes up, warnings are de-duplicated and
  only the media the document uses is kept
- the routers fan out the three compiles, send only broken pages and interactives to repair, and go on, fall back
  or fail
"""

import pytest
from support.lesson_data import make_interactive_plan, make_state
from support.media import png

from graph.codegen import DocumentAssembler
from graph.nodes.build import (
    AssembleDocumentNode,
    CodeFixer,
    CompilePageNode,
    PersistLessonNode,
    PrepareBuildNode,
    RenderCheckNode,
    RepairComponentNode,
    RepairPageNode,
)
from graph.nodes.build_routers import AssembledRouter, BuildRouter, RenderRouter
from graph.sandbox import RenderReport
from lessons.models import Lesson, MediaAsset, Stage

assembler = DocumentAssembler()
GOOD = "function Page_core() {\n  return <PageFrame title={LESSON.pages.core.title} />;\n}\n"
WIDGET = {
    "spec_id": "widget_core", "component_name": "Interactive_widget_core", "page": "core", "anchor": "s1",
    "kind": "simulation", "purpose": "p", "tsx": "function Interactive_widget_core() { return <div />; }\n",
}  # fmt: skip
ERROR = "line 1:0 [forbidden-global] `fetch` is not allowed in lesson code"


def built(lesson_state, **extra):
    """A state at the start of Stage C: everything authored, widgets built, pages not yet compiled."""
    full = make_state()
    keys = ("assessment", "plan", "pages", "final_test", "interactive_plan")
    return lesson_state | {k: full[k] for k in keys} | {"interactives": {"widget_core": WIDGET}} | extra


class TestCodeFixer:
    def test_clean_code_passes_without_a_model_call(self, ctx, gateway, lesson_state):
        code, errors = CodeFixer().fix(ctx, lesson_state, GOOD, contract="c", required=["Page_core"])

        assert (code, errors) == (GOOD, []) and gateway.called("code.repair") == []

    def test_fences_and_imports_are_stripped_before_the_check(self, ctx, lesson_state, sandbox):
        wrapped = "```tsx\nimport React from 'react';\n" + GOOD + "```"

        code, _ = CodeFixer().fix(ctx, lesson_state, wrapped, contract="c", required=["Page_core"])

        assert code == GOOD and sandbox.check_calls[0]["code"] == GOOD

    def test_failing_code_goes_to_the_repair_model_with_the_errors_and_the_contract(
        self, ctx, gateway, sandbox, lesson_state, events
    ):
        sandbox.check_script = [[ERROR], []]
        gateway.script("code.repair", GOOD)

        code, errors = CodeFixer().fix(ctx, lesson_state, "bad", contract="Declare Page_core", required=["Page_core"])

        assert (code, errors) == (GOOD, [])
        prompt = gateway.called("code.repair")[0].messages
        assert ERROR in prompt[1].content and "Declare Page_core" in prompt[0].content
        assert events.of_type("attempt")[0]["node"] == "code_fix_loop"

    def test_gives_up_after_the_attempt_budget_and_returns_the_remaining_errors(
        self, ctx, gateway, sandbox, lesson_state
    ):
        sandbox.check_script = [[ERROR]]
        gateway.script("code.repair", "still bad", "still bad again")

        code, errors = CodeFixer().fix(ctx, lesson_state, "bad", contract="c", required=["Page_core"])

        assert errors == [ERROR] and code.startswith("still bad again") and len(gateway.called("code.repair")) == 2

    def test_the_known_components_and_assets_are_passed_to_the_check(self, ctx, sandbox, lesson_state):
        CodeFixer().fix(ctx, lesson_state, GOOD, contract="c", required=["Page_core"], components=["Interactive_a"])

        assert sandbox.check_calls[0]["components"] == ["Interactive_a"]


class TestCompilePage:
    def branch(self, lesson_state, key="core"):
        return built(lesson_state, key=key)

    def test_returns_the_page_code_that_passed_the_loop(self, ctx, gateway, runtime, lesson_state):
        gateway.script("page.compile", "```tsx\n" + GOOD + "```")

        update = CompilePageNode()(self.branch(lesson_state), runtime)

        assert update == {"page_code": {"core": GOOD}}

    def test_the_prompt_lists_what_to_place_on_the_page(self, ctx, gateway, runtime, lesson_state):
        gateway.script("page.compile", GOOD)

        CompilePageNode()(self.branch(lesson_state), runtime)

        user = gateway.called("page.compile")[0].messages[1].content
        assert '<Interactive_widget_core /> after section "s1"' in user and "Page key: core" in user

    def test_code_that_keeps_failing_becomes_the_standard_layout_with_a_warning(
        self, ctx, gateway, runtime, lesson_state, sandbox
    ):
        sandbox.check_script = [[ERROR]]
        gateway.script("page.compile", "bad").script("code.repair", "worse", "worst")

        update = CompilePageNode()(self.branch(lesson_state), runtime)

        assert "<Interactive_widget_core />" in update["page_code"]["core"]  # the template places the widget
        assert update["warnings"][0].startswith("The core page uses the standard layout: generated code kept failing")


class TestAssemble:
    def pages(self):
        return {k: assembler.template_page(k, {}) for k in ("introduction", "core", "advanced")}

    def test_a_clean_document_is_assembled_with_the_test_page_and_the_wrapped_widgets(
        self, runtime, lesson_state, sandbox
    ):
        update = AssembleDocumentNode()(built(lesson_state, page_code=self.pages()), runtime)

        document = update["document_code"]
        assert "function Page_test()" in document and 'withBoundary("Interactive_widget_core"' in document
        assert sandbox.check_calls[0]["required"] == ["LessonDocument"] and set(update) == {"document_code"}

    def test_a_clash_between_parts_falls_back_to_template_pages_once(self, runtime, lesson_state, sandbox):
        sandbox.check_script = [["line 3:0 [not-in-scope] `X` is not defined"], []]

        update = AssembleDocumentNode()(built(lesson_state, page_code={k: "custom" for k in self.pages()}), runtime)

        assert (
            update["page_code"].keys() == {"introduction", "core", "advanced"}
            and "custom" not in update["document_code"]
        )
        assert update["warnings"] == ["Pages use the standard layout: the generated pages clashed"]

    def test_a_document_that_still_fails_is_an_error_with_the_node_to_resume_at(self, runtime, lesson_state, sandbox):
        sandbox.check_script = [["line 1:0 [syntax] x"]]

        update = AssembleDocumentNode()(built(lesson_state, page_code=self.pages()), runtime)

        assert update["document_code"] is None and update["failed_node"] == "assemble_document"
        assert update["error"] == "The lesson document does not pass the code checks: line 1:0 [syntax] x"
        assert update["retry_keys"] == ["render"]


def clean_report():
    return RenderReport(ok=True, pages={k: [] for k in ("introduction", "core", "advanced", "test")})


class TestRenderCheck:
    def state(self, lesson_state, **extra):
        return built(lesson_state, document_code="doc", page_code={}, **extra)

    def test_sends_the_public_lesson_data_with_placeholder_media_urls_and_the_media_files(
        self, runtime, lesson_state, sandbox
    ):
        sandbox.render_reports = [clean_report()]
        ref = {"asset_id": "a-1", "file": "lesson-media/x/a-1.png", "caption": "c", "alt_text": "a", "title": "t"}

        update = RenderCheckNode()(self.state(lesson_state, media={"widget_introduction": ref}), runtime)

        call = sandbox.render_calls[0]
        assert call["pages"] == ["introduction", "core", "advanced", "test"] and call["code"] == "doc"
        assert call["media_files"]["a-1"].endswith("lesson-media/x/a-1.png")
        assert call["data"]["media"]["a-1"]["url"] == "https://media.invalid/a-1"
        assert "correct_index" not in str(call["data"]["final_test"])
        assert update["render_report"]["decision"] == "pass" and update["attempts"] == {"render": 1}

    def test_a_repair_decision_only_records_the_report(self, runtime, lesson_state, sandbox, events):
        sandbox.render_reports = [RenderReport(ok=False, pages={"core": ["Runtime error: boom"]})]

        update = RenderCheckNode()(self.state(lesson_state), runtime)

        assert update["render_report"]["decision"] == "repair" and "error" not in update
        assert events.of_type("attempt")[0] == {
            "type": "attempt", "node": "render_check", "attempt": 2, "reason": "core: Runtime error: boom",
        }  # fmt: skip

    def test_a_fallback_carries_its_state_changes_and_a_warning(self, runtime, lesson_state, sandbox):
        sandbox.render_reports = [RenderReport(ok=False, pages={"core": ["boom"]})]

        update = RenderCheckNode()(self.state(lesson_state, attempts={"render": 2}), runtime)

        assert (
            update["render_report"]["decision"] == "fallback" and "function Page_core()" in update["page_code"]["core"]
        )
        assert update["warnings"] == ["Sandbox check: standard layout for core"] and "_warning" not in update

    def test_a_failure_sets_the_error_and_the_node_to_resume_at(self, runtime, lesson_state, sandbox):
        sandbox.render_reports = [RenderReport(ok=False, pages={"core": ["still broken"]})]

        update = RenderCheckNode()(self.state(lesson_state, attempts={"render": 3}), runtime)

        assert update["error"] == "The lesson failed the sandbox render check: core: still broken"
        assert (update["failed_node"], update["retry_keys"]) == ("assemble_document", ["render"])


class TestRepairs:
    def test_a_page_repair_tells_the_model_what_the_browser_reported(self, ctx, gateway, runtime, lesson_state):
        gateway.script("code.repair", GOOD)
        data = built(lesson_state, key="core", feedback=["Runtime error: x is undefined"], page_code={"core": "old"})

        update = RepairPageNode()(data, runtime)

        assert update == {"page_code": {"core": GOOD}}
        assert "In the browser: Runtime error: x is undefined" in gateway.called("code.repair")[0].messages[1].content

    def test_a_page_repair_that_fails_falls_back_to_the_template(self, ctx, gateway, runtime, lesson_state, sandbox):
        sandbox.check_script = [[ERROR]]
        gateway.script("code.repair", "a", "b", "c")
        data = built(lesson_state, key="core", feedback=["boom"], page_code={"core": "old"})

        update = RepairPageNode()(data, runtime)

        assert "function Page_core()" in update["page_code"]["core"]
        assert update["warnings"] == ["The core page uses the standard layout after a failed repair"]

    def test_a_repaired_component_replaces_the_old_one(self, ctx, gateway, runtime, lesson_state):
        fixed = "function Interactive_widget_core() { return <b>fixed</b>; }\n"
        gateway.script("code.repair", fixed)
        data = built(lesson_state, key="widget_core", item=WIDGET, feedback=["boom"])

        update = RepairComponentNode()(data, runtime)

        assert update == {"interactives": {"widget_core": WIDGET | {"tsx": fixed}}}

    def test_a_component_that_cannot_be_repaired_is_dropped_with_a_warning(
        self, ctx, gateway, runtime, lesson_state, sandbox
    ):
        sandbox.check_script = [[ERROR]]
        gateway.script("code.repair", "a", "b", "c")
        data = built(lesson_state, key="widget_core", item=WIDGET, feedback=["boom"])

        update = RepairComponentNode()(data, runtime)

        assert update["interactives"] == {"widget_core": None}
        assert update["warnings"] == ['Dropped the interactive "widget_core" after a failed repair']


class TestPersist:
    def state(self, lesson_state, **extra):
        pages = {k: assembler.template_page(k, {}) for k in ("introduction", "core", "advanced")}
        return built(lesson_state, document_code="THE DOCUMENT", page_code=pages, **extra)

    def test_the_lesson_becomes_ready_with_its_code_and_parts(self, lesson, runtime, lesson_state):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON, code_version=2)

        PersistLessonNode()(self.state(lesson_state, warnings=["a", "b", "a"]), runtime)

        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, stored.code, stored.code_version) == (Stage.READY, "THE DOCUMENT", 3)
        assert set(stored.code_parts["pages"]) == {"introduction", "core", "advanced"}
        assert stored.code_parts["interactives"] == {"Interactive_widget_core": WIDGET["tsx"]}
        assert stored.warnings == ["a", "b"] and len(stored.pages) == 3 and len(stored.final_test["questions"]) == 10

    def test_only_the_media_the_document_uses_is_kept(self, lesson, runtime, lesson_state, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)
        MediaAsset.objects.create(
            lesson=lesson, spec_id="old", kind="image", file="old.png", mime_type="image/png", source="wikimedia"
        )
        (tmp_path / "old.png").write_bytes(png())
        keep = {
            "asset_id": "5a1b6f0e-5d6e-4ac1-9a6f-0a1b2c3d4e5f", "kind": "image", "file": "new.png",
            "mime_type": "image/png", "width": 1, "height": 1, "source": "wikimedia", "source_url": "",
            "title": "t", "license": "cc0", "attribution": "a", "alt_text": "", "caption": "", "verified": False,
        }  # fmt: skip

        PersistLessonNode()(self.state(lesson_state, media={"widget_introduction": keep}), runtime)

        assert [a.spec_id for a in MediaAsset.objects.filter(lesson=lesson)] == ["widget_introduction"]
        assert not (tmp_path / "old.png").exists()  # the post-delete signal removed the file


class TestRouters:
    def test_prepare_build_declares_the_stage_and_changes_nothing(self, lesson, runtime, lesson_state):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED)

        assert PrepareBuildNode()(lesson_state, runtime) == {}
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.GENERATING_LESSON

    def test_the_build_router_compiles_the_three_pages_in_parallel_with_the_widgets(self, lesson_state):
        sends = BuildRouter()(built(lesson_state))

        assert [(s.node, s.arg["key"]) for s in sends] == [
            ("compile_page", k) for k in ("introduction", "core", "advanced")
        ]
        assert all(s.arg["interactives"] == {"widget_core": WIDGET} and s.arg["plan"] for s in sends)

    def test_an_assembled_document_goes_to_the_render_check_and_none_fails_the_run(self):
        assert AssembledRouter()({"document_code": "doc"}) == "render_check"
        assert AssembledRouter()({"document_code": None, "error": "x"}) == "mark_failed"

    def state(self, lesson_state, decision, pages=None, components=None):
        report = {"decision": decision, "pages": pages or {}, "components": components or {}}
        return built(
            lesson_state, render_report=report, page_code={k: f"code {k}" for k in ("introduction", "core", "advanced")}
        )

    @pytest.mark.parametrize(
        ("decision", "target"), [("pass", "persist_lesson"), ("fallback", "assemble_document"), ("fail", "mark_failed")]
    )
    def test_pass_fallback_and_fail_go_where_they_should(self, lesson_state, decision, target):
        assert RenderRouter()(self.state(lesson_state, decision)) == target

    def test_a_repair_goes_only_to_the_broken_pages_and_interactives(self, lesson_state):
        state = self.state(
            lesson_state, "repair", pages={"core": ["boom"], "advanced": [], "test": ["x"]},
            components={"Interactive_widget_core": ["crash"], "Interactive_ghost": ["nope"]},
        )  # fmt: skip

        sends = RenderRouter()(state)

        assert [(s.node, s.arg["key"]) for s in sends] == [("repair_page", "core"), ("repair_component", "widget_core")]
        page, component = sends
        assert page.arg["feedback"] == ["boom"] and page.arg["page_code"] == "code core"
        assert component.arg["item"] == WIDGET and component.arg["feedback"] == ["crash"]


def test_the_interactive_plan_used_here_has_a_core_widget():
    assert [s["id"] for s in make_interactive_plan()["specs"]][1] == "widget_core"

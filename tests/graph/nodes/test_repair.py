"""Unit under test: the runtime repair nodes in `graph.nodes.repair`: loading the lesson and finding what crashed,
repairing it with the model, assembling and checking the repaired document, and saving it as a new version.

Why: a runtime repair edits a lesson learners are reading, so the failure modes matter more than the happy path: a stale
report must not overwrite a newer lesson, a repair that changes nothing or loses content must be refused, a repair that
fails must leave the lesson exactly as it was, and a good one must keep the old code as a version to go back to.

Use cases:
- load_repair: finds the target and loads what later steps need; refuses a lesson that is not ready, a stale
  `code_version` and an error that cannot be traced to a part
- repair_runtime: asks `runtime.repair` for the crashed interactive or page with the error and the contract, holds the
  answer to the code checks, and replaces only that part; refuses code that still fails or did not change
- assemble_repaired: assembles the document with the test page; refuses a document that fails the code checks
- regression_check: lets a faithful repair through and refuses one that dropped content
- verify_repair: records a clean render; refuses a repair that still fails in the browser, saying what failed
- save_repair: keeps the old code as a LessonVersion, stores the new code under the next code_version, and refuses when
  the lesson moved on meanwhile
"""

import pytest
from support.fixtures import budget_snapshot
from support.lesson_data import make_state

from graph.codegen import DocumentAssembler
from graph.errors import RepairFailed
from graph.nodes.repair import (
    AssembleRepairedNode,
    LoadRepairNode,
    RegressionCheckNode,
    RepairRuntimeNode,
    SaveRepairNode,
    VerifyRepairNode,
)
from graph.sandbox import RenderReport
from lessons.models import Lesson, LessonVersion, Stage

assembler = DocumentAssembler()
PAGE = "<Section><Interactive_widget_core />{page.sections.map((s) => s.id)}</Section>"
OLD_PARTS = {
    "pages": {
        "introduction": "function Page_introduction() { return null; }",
        "core": "function Page_core() { return " + PAGE + "; }",
        "advanced": "function Page_advanced() { return null; }",
    },
    "interactives": {"Interactive_widget_core": "function Interactive_widget_core() { return null.x; }"},
}  # fmt: skip
ERROR = {"message": "Interactive_widget_core crashed: x is undefined", "page": "core"}
CODE_ERROR = "line 1:0 [forbidden-global] `fetch` is not allowed in lesson code"


@pytest.fixture
def ready(lesson, lesson_state):
    """A ready lesson with stored code, and the state `load_repair` would start from."""
    full = make_state()
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, code="OLD DOCUMENT", code_parts=OLD_PARTS, code_version=3,
        plan=full["plan"], pages=full["pages"], final_test=full["final_test"],
        config_snapshot=budget_snapshot(), settings_snapshot=lesson_state["settings"],
    )  # fmt: skip
    return lesson_state | {
        "plan": full["plan"], "pages": full["pages"], "final_test": full["final_test"], "media": {},
        "code_parts": OLD_PARTS, "repair_error": ERROR, "expected_code_version": 3,
        "repair_target": {"kind": "component", "key": "Interactive_widget_core"},
    }  # fmt: skip


class TestLoad:
    def start(self, ready):
        return {k: ready[k] for k in ("lesson_id", "repair_error", "expected_code_version")}

    def test_it_loads_the_lesson_and_names_the_target(self, ready, runtime):
        update = LoadRepairNode()(self.start(ready), runtime)

        assert update["repair_target"] == {"kind": "component", "key": "Interactive_widget_core"}
        assert update["code_parts"] == OLD_PARTS and update["pages"] == ready["pages"] and update["media"] == {}
        assert update["snapshot"] == budget_snapshot() and set(update["plan"]) >= {"title", "pages"}

    def test_a_lesson_that_is_not_ready_is_refused(self, ready, runtime, lesson):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED)

        with pytest.raises(RepairFailed, match="not in a state that can be repaired"):
            LoadRepairNode()(self.start(ready), runtime)

    def test_a_stale_code_version_is_refused(self, ready, runtime):
        with pytest.raises(RepairFailed, match="changed since the error was reported"):
            LoadRepairNode()(self.start(ready) | {"expected_code_version": 2}, runtime)

    def test_an_error_that_cannot_be_traced_is_refused(self, ready, runtime):
        with pytest.raises(RepairFailed, match="could not be traced"):
            LoadRepairNode()(self.start(ready) | {"repair_error": {"message": "boom"}}, runtime)


class TestRepairRuntime:
    FIXED = "function Interactive_widget_core() { return <b>fixed</b>; }\n"

    def test_a_crashed_interactive_is_repaired_and_only_it_is_replaced(self, ready, runtime, gateway):
        gateway.script("runtime.repair", self.FIXED)

        update = RepairRuntimeNode()(ready, runtime)

        assert update["repaired_parts"]["interactives"] == {"Interactive_widget_core": self.FIXED}
        assert update["repaired_parts"]["pages"] == OLD_PARTS["pages"]
        prompt = gateway.called("runtime.repair")[0].messages
        assert "Interactive_widget_core crashed" in prompt[1].content and "return null.x" in prompt[1].content
        assert "function Interactive_widget_core()" in prompt[0].content

    def test_a_crashed_page_is_repaired_with_the_interactives_it_uses_in_the_contract(self, ready, runtime, gateway):
        fixed = "function Page_core() { return <Interactive_widget_core />; }\n"
        gateway.script("runtime.repair", fixed)
        state = ready | {"repair_target": {"kind": "page", "key": "core"}}

        update = RepairRuntimeNode()(state, runtime)

        assert update["repaired_parts"]["pages"]["core"] == fixed
        assert "Interactive_widget_core" in gateway.called("runtime.repair")[0].messages[0].content

    def test_code_that_still_fails_the_checks_is_refused(self, ready, runtime, gateway, sandbox):
        sandbox.check_script = [[CODE_ERROR]]
        gateway.script("runtime.repair", "bad").script("code.repair", "worse", "worst")

        with pytest.raises(RepairFailed, match="still fails the checks .*fetch"):
            RepairRuntimeNode()(ready, runtime)

    def test_the_same_code_back_is_refused(self, ready, runtime, gateway):
        gateway.script("runtime.repair", OLD_PARTS["interactives"]["Interactive_widget_core"])

        with pytest.raises(RepairFailed, match="same code"):
            RepairRuntimeNode()(ready, runtime)


class TestAssemble:
    def test_the_repaired_parts_are_assembled_with_the_test_page(self, ready, runtime, sandbox):
        update = AssembleRepairedNode()(ready | {"repaired_parts": OLD_PARTS}, runtime)

        assert (
            "function Page_test()" in update["document_code"] and "function LessonDocument()" in update["document_code"]
        )
        assert sandbox.check_calls[0]["required"] == ["LessonDocument"]

    def test_a_document_that_fails_the_checks_is_refused(self, ready, runtime, sandbox):
        sandbox.check_script = [[CODE_ERROR]]

        with pytest.raises(RepairFailed, match="does not pass the code checks .*fetch"):
            AssembleRepairedNode()(ready | {"repaired_parts": OLD_PARTS}, runtime)


class TestRegression:
    def test_a_faithful_repair_passes(self, ready, runtime):
        fixed = {**OLD_PARTS, "interactives": {"Interactive_widget_core": "function Interactive_widget_core() {}"}}

        assert RegressionCheckNode()(ready | {"repaired_parts": fixed}, runtime) == {}

    def test_a_repair_that_dropped_content_is_refused(self, ready, runtime):
        fixed = {**OLD_PARTS, "pages": {**OLD_PARTS["pages"], "core": "function Page_core() { return null; }"}}

        with pytest.raises(RepairFailed, match="dropped content from the core page: all sections, interactive"):
            RegressionCheckNode()(ready | {"repaired_parts": fixed}, runtime)


class TestVerify:
    def state(self, ready):
        return ready | {"document_code": "DOC"}

    def test_a_clean_render_is_recorded(self, ready, runtime, sandbox):
        sandbox.render_reports = [RenderReport(ok=True, pages={"core": []})]

        update = VerifyRepairNode()(self.state(ready), runtime)

        assert update["render_report"]["ok"] is True
        call = sandbox.render_calls[0]
        assert call["pages"] == ["introduction", "core", "advanced", "test"] and call["code"] == "DOC"

    def test_a_repair_that_still_fails_in_the_browser_is_refused_and_says_why(self, ready, runtime, sandbox):
        sandbox.render_reports = [RenderReport(ok=False, pages={"core": ["Runtime error: boom"]})]

        with pytest.raises(RepairFailed, match="still fails in the browser check .*core: Runtime error: boom"):
            VerifyRepairNode()(self.state(ready), runtime)


class TestSave:
    def state(self, ready, **extra):
        return ready | {"document_code": "NEW DOCUMENT", "repaired_parts": {**OLD_PARTS, "interactives": {}}} | extra

    def test_the_old_code_becomes_a_version_and_the_new_code_the_next_one(self, ready, runtime, lesson):
        SaveRepairNode()(self.state(ready), runtime)

        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.code, stored.code_version, stored.stage) == ("NEW DOCUMENT", 4, Stage.READY)
        assert stored.code_parts["interactives"] == {}
        version = LessonVersion.objects.get(lesson=lesson)
        assert (version.code_version, version.code, version.code_parts) == (3, "OLD DOCUMENT", OLD_PARTS)
        assert version.reason == "Runtime repair: Interactive_widget_core crashed: x is undefined"

    def test_a_lesson_that_moved_on_is_left_alone(self, ready, runtime, lesson):
        Lesson.objects.filter(pk=lesson.pk).update(code_version=4)

        with pytest.raises(RepairFailed, match="changed while it was being repaired"):
            SaveRepairNode()(self.state(ready), runtime)

        assert Lesson.objects.get(pk=lesson.pk).code == "OLD DOCUMENT" and not LessonVersion.objects.exists()

    def test_a_long_error_message_is_cut_for_the_reason(self, ready, runtime, lesson):
        SaveRepairNode()(self.state(ready, repair_error={"message": "x" * 500}), runtime)

        assert len(LessonVersion.objects.get(lesson=lesson).reason) == 300


def test_the_standard_test_page_is_not_part_of_the_stored_pages():
    assert "test" not in OLD_PARTS["pages"] and "function Page_test()" in assembler.test_page()

"""Unit under test: the Stage C segment of the lesson-flow graph (`graph.builders.BuildSegment`) wired after Stage B:
prepare_build → three page compiles in parallel → assemble → render check → repair only what broke → persist.

Why: the nodes pass their own tests, but the wiring decides that a page which breaks in the browser is repaired
*alone*, that the repair loop is bounded and ends in the standard layout, that a lesson only becomes ready after a clean
render, and that a run which cannot be fixed fails with a reason and resumes at the assembly. These tests run the real
graph with a scripted gateway and the fake sandbox (the browser itself is tested in test_sandbox.py).

Use cases:
- after Stage B the three pages are compiled in parallel, assembled, render-checked and saved: the lesson is ready with
  its code, code parts and code_version 1
- a page that breaks in the browser is repaired alone (the others are not touched) and the lesson is then saved
- a page that keeps breaking falls back to the standard layout after the repair rounds, with a warning
- a lesson that still fails after the fallback fails the run with the render problems; Retry resumes at the assembly
  and, once the browser is happy, saves the lesson
"""

import re

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command
from support.driver import GraphDriver
from support.lesson_data import make_final_test, make_interactive_plan, make_pages, make_plan
from support.media import make_library, result

from graph.builders import AuthorSegment, BuildSegment, DiagnoseSegment
from graph.sandbox import RenderReport
from lessons.models import Lesson, Stage

pytestmark = pytest.mark.django_db(transaction=True)

ASSESSMENT = {
    "level": "beginner", "known_concepts": ["Searching a list"], "gaps": ["The loop invariant"],
    "prerequisites_to_cover": [], "start_point": "Halving the range", "author_notes": "Gentle.", "confidence": "medium",
}  # fmt: skip
REPORT = {
    "topic_relevance": 5, "level_fit": 5, "prerequisite_coverage": 5, "factual_accuracy": 5,
    "interactive_relevance": 5, "issues": [], "passed": True,
}  # fmt: skip
PAGE_KEYS = ("introduction", "core", "advanced")
CLEAN = RenderReport(ok=True, pages={k: [] for k in PAGE_KEYS})
CORE_BROKEN = RenderReport(ok=False, pages={"core": ["Runtime error: x is undefined"]})


def page_code(key):
    return f"function Page_{key}() {{\n  return <PageFrame title={{LESSON.pages.{key}.title}} />;\n}}\n"


def page_key(messages):
    return re.search(r"Page key: (\w+)", messages[1].content).group(1)


def search():
    return AIMessage(content="", tool_calls=[{"name": "search_wikimedia", "args": {"query": "amoeba"}, "id": "s1"}])


def submit(r):
    candidate = {k: r[k] for k in ("source", "file_url", "page_url", "title", "license", "attribution")} | {"why": "ok"}
    return AIMessage(content="", tool_calls=[{"name": "submit_media", "args": {"candidates": [candidate]}, "id": "c1"}])


def component_for(messages):
    name = re.search(r"Component name: (\w+)", messages[1].content).group(1)
    return {
        "spec_id": name.removeprefix("Interactive_"),
        "component_name": name,
        "tsx": f"function {name}() {{ return null; }}",
    }


@pytest.fixture
def flow(lesson, ctx, lesson_state, gateway, valid_bundle, tmp_path, sandbox):
    """The whole flow up to the first quiz, with Stage B and the page compiler scripted to produce valid output."""
    ctx.media = make_library(tmp_path, [result(1)])
    plan = make_interactive_plan()
    plan["specs"][0] |= {"kind": "image", "media_query": "amoeba binary fission"}
    gateway.script("diagnostic.generate", valid_bundle).script("learner.assess", ASSESSMENT)
    gateway.script("lesson.plan", make_plan()).script("interactive.plan", plan)
    gateway.script("media.search", search(), submit(result(1))).script("alignment.judge", REPORT)
    gateway.respond(
        "page.generate", lambda m: make_pages()[re.search(r'Write the "(\w+)" page', m[0].content).group(1)]
    )
    gateway.respond("test.generate", lambda m: make_final_test())
    gateway.respond("interactive.generate", component_for)
    gateway.respond("page.compile", lambda m: page_code(page_key(m)))
    sandbox.render_reports = [CLEAN]
    return GraphDriver(lesson, ctx, lesson_state, [DiagnoseSegment(), AuthorSegment(), BuildSegment()]).start()


def finish(flow):
    return flow.answer("diagnostic", right=5)


def test_after_stage_b_the_pages_are_compiled_assembled_checked_and_saved(flow, lesson, sandbox):
    finish(flow)

    assert flow.interrupt is None
    for node in ("prepare_build", "assemble_document", "render_check", "persist_lesson"):
        assert node in flow.nodes
    assert flow.nodes.count("compile_page") == 3 and "repair_page" not in flow.nodes
    stored = Lesson.objects.get(pk=lesson.pk)
    assert (stored.stage, stored.code_version, stored.warnings) == (Stage.READY, 1, [])
    assert "function LessonDocument()" in stored.code and "Page_test" not in stored.code
    assert set(stored.code_parts["pages"]) == set(PAGE_KEYS) and len(sandbox.render_calls) == 1


def test_a_page_that_breaks_in_the_browser_is_repaired_alone_and_the_lesson_is_saved(flow, lesson, gateway, sandbox):
    sandbox.render_reports = [CORE_BROKEN, CLEAN]
    repaired = page_code("core").replace("<PageFrame", "<PageFrame /* repaired */ ")
    gateway.script("code.repair", repaired)

    finish(flow)

    assert flow.nodes.count("repair_page") == 1 and flow.nodes.count("compile_page") == 3
    repair = gateway.called("code.repair")[0].messages[1].content
    assert "In the browser: Runtime error: x is undefined" in repair
    stored = Lesson.objects.get(pk=lesson.pk)
    assert stored.stage == Stage.READY and "/* repaired */" in stored.code_parts["pages"]["core"]
    assert "/* repaired */" not in stored.code_parts["pages"]["introduction"]


def test_a_page_that_keeps_breaking_falls_back_to_the_standard_layout_with_a_warning(flow, lesson, gateway, sandbox):
    sandbox.render_reports = [CORE_BROKEN, CORE_BROKEN, CORE_BROKEN, CLEAN]
    gateway.respond("code.repair", lambda m: page_code("core"))

    finish(flow)

    assert flow.nodes.count("repair_page") == 2 and flow.nodes.count("render_check") == 4
    stored = Lesson.objects.get(pk=lesson.pk)
    assert stored.stage == Stage.READY and "page.sections.map" in stored.code_parts["pages"]["core"]
    assert stored.warnings == ["Sandbox check: standard layout for core"]


def test_a_lesson_that_still_fails_fails_the_run_and_retry_resumes_at_the_assembly(flow, lesson, gateway, sandbox):
    sandbox.render_reports = [CORE_BROKEN]
    gateway.respond("code.repair", lambda m: page_code("core"))

    finish(flow)

    assert flow.interrupt["kind"] == "retry" and flow.nodes[-1] == "mark_failed"
    failed = Lesson.objects.get(pk=lesson.pk)
    assert failed.stage == Stage.FAILED and "failed the sandbox render check: core: Runtime error" in failed.error

    sandbox.render_reports = [CLEAN]
    flow.stream(Command(resume=True))

    assert flow.interrupt is None and Lesson.objects.get(pk=lesson.pk).stage == Stage.READY
    assert flow.nodes.count("compile_page") == 3  # the pages were not written again

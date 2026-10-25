"""Unit under test: the `runtime_repair` graph (`graph.builders.RuntimeRepairGraphBuilder`): a ready lesson that
crashed in the learner's browser is repaired in place.

Why: the nodes pass their own tests, but the wiring decides that a refused repair leaves the lesson exactly as it was
and that a good one is checked in the order cheap-to-expensive and saved as a new version. The last test runs the real
sandbox and headless Chromium on a lesson whose interactive really throws, which is the acceptance case: a lesson broken
on purpose is repaired.

Use cases:
- a crashed interactive is repaired: the nodes run in order and the lesson gets a new code_version with the old code
  kept as a version
- a repair the checks refuse (content dropped, browser still failing) ends the run with its reason and changes nothing
- with the real sandbox, an interactive that throws when rendered is replaced by a working one and the lesson saves
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from support.fakes import ListEvents
from support.fixtures import budget_snapshot
from support.lesson_data import make_state

from graph.builders import RuntimeRepairGraphBuilder
from graph.codegen import DocumentAssembler
from graph.context import FlowContext
from graph.errors import RepairFailed
from graph.sandbox import RenderReport, SandboxRunner
from lessons.models import Lesson, LessonVersion, Stage

pytestmark = pytest.mark.django_db(transaction=True)

assembler = DocumentAssembler()
BROKEN = "function Interactive_widget_core() {\n  throw new Error('boom');\n}\n"
FIXED = "function Interactive_widget_core() {\n  return <p>Working widget</p>;\n}\n"
ERROR = {"message": "Interactive_widget_core crashed: boom", "page": "core"}
NODES = ["load_repair", "repair_runtime", "assemble_repaired", "regression_check", "verify_repair", "save_repair"]


@pytest.fixture
def ready(lesson, lesson_state):
    """A ready lesson whose core page places a widget that throws."""
    full = make_state()
    placements = {"core": {full["pages"]["core"]["sections"][0]["id"]: ["<Interactive_widget_core />"]}}
    pages = {k: assembler.template_page(k, placements.get(k, {})) for k in ("introduction", "core", "advanced")}
    parts = {"pages": pages, "interactives": {"Interactive_widget_core": BROKEN}}
    code = assembler.assemble(parts["interactives"], pages)
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, code=code, code_parts=parts, code_version=1, plan=full["plan"], pages=full["pages"],
        final_test=full["final_test"], config_snapshot=budget_snapshot(), settings_snapshot=lesson_state["settings"],
    )  # fmt: skip
    return lesson


def repair(lesson, ctx, error=ERROR):
    graph = RuntimeRepairGraphBuilder().build(InMemorySaver())
    config = {"configurable": {"thread_id": "repair"}}
    nodes = []
    start = {"lesson_id": str(lesson.id), "repair_error": error, "expected_code_version": 1}
    for chunk in graph.stream(start, config, context=ctx, stream_mode="updates"):
        nodes += list(chunk)
    return nodes


def test_a_crashed_interactive_is_repaired_and_the_old_code_kept_as_a_version(ready, ctx, gateway, sandbox):
    gateway.script("runtime.repair", FIXED)
    sandbox.render_reports = [RenderReport(ok=True, pages={"core": []})]

    nodes = repair(ready, ctx)

    assert nodes == NODES
    stored = Lesson.objects.get(pk=ready.pk)
    assert (stored.code_version, stored.stage) == (2, Stage.READY) and "Working widget" in stored.code
    assert stored.code_parts["interactives"] == {"Interactive_widget_core": FIXED}
    assert "boom" in LessonVersion.objects.get(lesson=ready, code_version=1).code


def test_a_repair_the_browser_refuses_changes_nothing(ready, ctx, gateway, sandbox):
    gateway.script("runtime.repair", FIXED)
    sandbox.render_reports = [RenderReport(ok=False, pages={"core": ["Runtime error: still broken"]})]
    before = Lesson.objects.get(pk=ready.pk)

    with pytest.raises(RepairFailed, match="still fails in the browser check"):
        repair(ready, ctx)

    stored = Lesson.objects.get(pk=ready.pk)
    assert (stored.code, stored.code_version) == (before.code, 1) and not LessonVersion.objects.exists()


def test_a_repair_that_drops_content_is_refused_before_the_browser_is_started(ready, ctx, gateway, sandbox):
    thin = "function Page_core() {\n  return <PageFrame title={LESSON.pages.core.title} />;\n}\n"
    gateway.script("runtime.repair", thin)

    with pytest.raises(RepairFailed, match="dropped content from the core page"):
        repair(ready, ctx, error={"message": "boom", "page": "core"})

    assert sandbox.render_calls == [] and Lesson.objects.get(pk=ready.pk).code_version == 1


@pytest.mark.skipif(not SandboxRunner().render_available(), reason="the lesson runtime is not built")
def test_with_the_real_sandbox_an_interactive_that_throws_is_replaced_by_one_that_works(ready, gateway):
    ctx = FlowContext(gateway=gateway, sandbox=SandboxRunner(), events=ListEvents(), run_id="run-1")
    gateway.script("runtime.repair", FIXED)

    nodes = repair(ready, ctx)

    assert nodes == NODES
    stored = Lesson.objects.get(pk=ready.pk)
    assert stored.code_version == 2 and "Working widget" in stored.code and "boom" not in stored.code

"""Unit under test: the Stage B segment of the lesson-flow graph (`graph.builders.AuthorSegment`) wired after Stage A:
plan → pages and test in parallel → interactives and media in parallel → alignment judge with targeted fixes.

Why: the nodes pass their own tests, but the wiring is what decides that a bad page is regenerated *alone*, that the
media agent and the widget writers run for the right specs, that a fix goes only to the flagged item, and that a run
which cannot be fixed fails with a reason and resumes where it gave up. These tests run the real graph with a scripted
gateway, a real media library over fake sources, and the fake sandbox.

Use cases:
- diagnostic → assessment → plan → three pages and the test → interactives (media agent for the image, code for the
  rest) → alignment passes: everything is saved on the lesson, the image is stored as a MediaAsset, the stage stays
  generating_lesson (Stage C is not wired yet)
- a page that fails its rules is regenerated alone, with the problems as feedback, and the others are not touched
- the alignment judge's fix goes only to the flagged page; the judge then runs again and passes
- when no media is found the spec becomes an SVG diagram and the lesson says so
- a widget whose code keeps failing the sandbox is dropped with a warning and the lesson goes on
- a plan that stays invalid fails the run; Retry resumes at plan_lesson with fresh counters
- a content review that keeps finding a major issue fails the run; Retry resumes at the judge
- the lesson's final data (plan, pages, test, interactive specs) is exactly what the stages produced
"""

import re

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command
from support.driver import GraphDriver
from support.lesson_data import make_final_test, make_interactive_plan, make_pages, make_plan
from support.media import make_library, result

from graph.builders import AuthorSegment, DiagnoseSegment
from lessons.models import Lesson, MediaAsset, Stage

pytestmark = pytest.mark.django_db(transaction=True)

ASSESSMENT = {
    "level": "beginner", "known_concepts": ["Searching a list"], "gaps": ["The loop invariant"],
    "prerequisites_to_cover": [], "start_point": "Halving the range", "author_notes": "Gentle.", "confidence": "medium",
}  # fmt: skip
REPORT = {
    "topic_relevance": 5, "level_fit": 5, "prerequisite_coverage": 5, "factual_accuracy": 5,
    "interactive_relevance": 5, "issues": [], "passed": True,
}  # fmt: skip


def plan_with_image():
    plan = make_interactive_plan()
    plan["specs"][0] |= {"kind": "image", "media_query": "amoeba binary fission"}
    return plan


def search():
    return AIMessage(content="", tool_calls=[{"name": "search_wikimedia", "args": {"query": "amoeba"}, "id": "s1"}])


def submit(r):
    candidate = {k: r[k] for k in ("source", "file_url", "page_url", "title", "license", "attribution")} | {"why": "ok"}
    return AIMessage(content="", tool_calls=[{"name": "submit_media", "args": {"candidates": [candidate]}, "id": "c1"}])


def page_for(messages):
    key = re.search(r'Write the "(\w+)" page', messages[0].content).group(1)
    return make_pages()[key]


def component_for(messages):
    name = re.search(r"Component name: (\w+)", messages[1].content).group(1)
    return {
        "spec_id": name.removeprefix("Interactive_"),
        "component_name": name,
        "tsx": f"function {name}() {{ return null; }}",
    }


@pytest.fixture
def flow(lesson, ctx, lesson_state, gateway, valid_bundle, tmp_path):
    """The flow up to the first quiz, with every Stage B node scripted to produce valid output."""
    ctx.media = make_library(tmp_path, [result(1)])
    gateway.script("diagnostic.generate", valid_bundle).script("learner.assess", ASSESSMENT)
    gateway.script("lesson.plan", make_plan()).script("interactive.plan", plan_with_image())
    gateway.script("media.search", search(), submit(result(1)))
    gateway.script("alignment.judge", REPORT)
    gateway.respond("page.generate", page_for).respond("test.generate", lambda m: make_final_test())
    gateway.respond("interactive.generate", component_for)
    driver = GraphDriver(lesson, ctx, lesson_state, [DiagnoseSegment(), AuthorSegment()])
    driver.start()
    return driver


def finish(flow):
    return flow.answer("diagnostic", right=5)


def test_the_whole_of_stage_b_runs_and_saves_what_it_wrote(flow, lesson, gateway):
    finish(flow)

    assert flow.interrupt is None
    for node in ("assess_learner", "plan_lesson", "validate_plan", "authored_join", "plan_interactives", "widgets_join",
                 "alignment_judge"):  # fmt: skip
        assert node in flow.nodes
    assert flow.nodes.count("write_page") == 3 and flow.nodes.count("write_test") == 1
    assert flow.nodes.count("find_media") == 1 and flow.nodes.count("build_interactive") == 2
    stored = Lesson.objects.get(pk=lesson.pk)
    assert (stored.title, stored.level, stored.stage) == ("Binary search", "beginner", Stage.GENERATING_LESSON)
    assert set(stored.pages) == {"introduction", "core", "advanced"} and len(stored.final_test["questions"]) == 10
    assert [s["kind"] for s in stored.interactive_plan["specs"]] == ["image", "simulation", "svg_diagram"]
    assert MediaAsset.objects.get(lesson=lesson).spec_id == "widget_introduction"
    assert flow.state()["alignment"]["decision"] == "pass"


def test_a_page_that_fails_its_rules_is_regenerated_alone_with_the_problems(flow, gateway):
    thin = make_pages()["core"]
    thin["sections"][0]["body"] = "Too short."

    def core_first_thin(messages):
        key = re.search(r'Write the "(\w+)" page', messages[0].content).group(1)
        if key == "core" and "REJECTED" not in messages[1].content:
            return thin
        return make_pages()[key]

    gateway.respond("page.generate", core_first_thin)

    finish(flow)

    calls = gateway.called("page.generate")
    keys = [re.search(r'Write the "(\w+)" page', c.messages[0].content).group(1) for c in calls]
    assert sorted(keys) == ["advanced", "core", "core", "introduction"]
    retry = next(c for c in calls if "REJECTED" in c.messages[1].content)
    assert "too thin" in retry.messages[1].content
    assert len(gateway.called("test.generate")) == 1  # the test was not touched
    assert flow.nodes.count("write_page") == 4


def test_the_judges_fix_goes_only_to_the_flagged_page_and_the_judge_runs_again(flow, gateway, lesson):
    flagged = {"target": "page", "target_id": "advanced", "severity": "major", "problem": "Wrong complexity claim",
               "fix_instruction": "Use O(log n)"}  # fmt: skip
    gateway.scripts["alignment.judge"] = [REPORT | {"factual_accuracy": 2, "issues": [flagged]}, REPORT]

    finish(flow)

    assert flow.nodes.count("alignment_judge") == 2 and flow.nodes.count("fix_item") == 1
    fixes = [c for c in gateway.called("page.generate") if "A reviewer flagged" in c.messages[1].content]
    assert len(fixes) == 1 and 'Write the "advanced" page' in fixes[0].messages[0].content
    assert "Wrong complexity claim" in fixes[0].messages[1].content and "Use O(log n)" in fixes[0].messages[1].content
    assert len(gateway.called("test.generate")) == 1 and len(gateway.called("interactive.generate")) == 2
    assert flow.state()["alignment"]["decision"] == "pass" and flow.state()["alignment"]["round"] == 2


def test_no_media_found_draws_an_svg_diagram_and_says_so(flow, gateway, ctx, tmp_path, lesson):
    ctx.media = make_library(tmp_path, [])
    gateway.scripts["media.search"] = [search(), submit(result(1)), submit(result(1))]  # nothing was ever returned

    finish(flow)

    stored = Lesson.objects.get(pk=lesson.pk)
    assert flow.interrupt is None and not MediaAsset.objects.exists()
    assert flow.state()["widget_kinds"] == {"widget_introduction": "svg_diagram"}
    assert (
        'No suitable image found for "widget_introduction": drawing an SVG diagram instead' in flow.state()["warnings"]
    )
    assert "widget_introduction" in flow.state()["interactives"]
    assert [s["kind"] for s in stored.interactive_plan["specs"]][0] == "svg_diagram"


def test_a_widget_that_keeps_failing_the_sandbox_is_dropped_with_a_warning(flow, sandbox, lesson):
    sandbox.failing_components = {"Interactive_widget_core"}

    finish(flow)

    assert flow.interrupt is None
    assert 'Dropped the interactive "widget_core": it kept failing the code checks' in flow.state()["warnings"]
    specs = {s["id"]: s for s in Lesson.objects.get(pk=lesson.pk).interactive_plan["specs"]}
    assert specs["widget_core"]["dropped"] is True and specs["widget_advanced"]["dropped"] is False
    assert "widget_core" not in flow.state()["interactives"]


def test_a_plan_that_stays_invalid_fails_the_run_and_retry_resumes_at_planning(flow, gateway, lesson):
    bad = make_plan()
    bad["pages"].pop()
    gateway.scripts["lesson.plan"] = [bad, bad, make_plan()]
    gateway.scripts["interactive.plan"] = [plan_with_image()]

    finish(flow)

    assert flow.interrupt["kind"] == "retry" and flow.nodes[-1] == "mark_failed"
    failed = Lesson.objects.get(pk=lesson.pk)
    assert failed.stage == Stage.FAILED and "The lesson plan still failed its checks" in failed.error

    flow.stream(Command(resume=True))

    assert flow.interrupt is None and flow.state()["alignment"]["decision"] == "pass"
    assert len(gateway.called("lesson.plan")) == 3


def test_a_content_review_that_keeps_finding_a_major_issue_fails_the_run_and_retry_resumes_at_the_judge(
    flow, gateway, lesson
):
    major = {"target": "page", "target_id": "core", "severity": "major", "problem": "A factual error",
             "fix_instruction": "Correct it"}  # fmt: skip
    failing = REPORT | {"factual_accuracy": 1, "issues": [major]}
    gateway.scripts["alignment.judge"] = [failing, failing, failing, REPORT]

    finish(flow)

    assert flow.interrupt["kind"] == "retry"
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.FAILED
    assert (
        "The content review found problems it could not fix: A factual error" in Lesson.objects.get(pk=lesson.pk).error
    )

    flow.stream(Command(resume=True))

    assert flow.interrupt is None and flow.state()["alignment"]["decision"] == "pass"
    assert len(gateway.called("lesson.plan")) == 1  # resumed at the judge, not from the plan

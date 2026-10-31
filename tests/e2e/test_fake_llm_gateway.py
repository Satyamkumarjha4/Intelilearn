"""Unit under test: the real `Gateway` and LangChain client driven against `tests/e2e/fake_llm_server.py`.

Why: every other test fakes the chat model, so none proves that the gateway's real request (structured output through
a real OpenAI-compatible client, the registry's parameters, token logging) is understood and answered correctly over
HTTP. This does, offline, and it validates the fake that the browser walk-through relies on.

Use cases:
- a structured-output call (json_schema) returns a valid DiagnosticBundle, and the call is logged with tokens
- a function-calling model gets the same bundle through a tool call
- the prerequisite planner's list is served, valid and named for the topic, and a lesson plan for a Beginner whose
  prerequisites it planned teaches them on the introduction page, passing the real plan validator with that shape
- the three study sheets come back valid and pass the study validator for the concepts in the prompt
- every Stage B output (plan, page, test, interactive plan, alignment report) passes the real validators, and each kind
  of widget code passes the real sandbox check
- the media agent finds, downloads and stores a picture end to end: real gateway and client, real library and
  downloader, the fake's Wikimedia API and image
- a page compiled through the text path (no schema) keeps every section and places the widgets, and passes the real
  sandbox check
- a grading prompt is answered with one valid grade per question, within its marks, which the real validator accepts
- a crashed interactive is answered with a replacement that passes the real sandbox check
- a text prompt the fake does not know is refused
- a schema the fake does not know is refused, and the gateway reports every model failed
- the quick quiz's steps are served: the topic judge (calculation and programming words), the calibration pool (a bundle
  with no prerequisite half that passes the pool rules), and a quiz's batch of questions for its cells, which pass the
  real batch validator
"""

import re

import pytest
from e2e.fake_llm_server import FakeLLMServer
from pydantic import BaseModel
from support.lesson_data import make_assessment, make_state

from graph.codegen import DocumentAssembler
from graph.context import FlowContext
from graph.levels import Level, LevelScheme
from graph.media import MediaLibrary
from graph.nodes.media_agent import MediaFinder
from graph.prompts import (
    AlignmentPrompt,
    CompilePagePrompt,
    DiagnosticPrompt,
    GenerateInteractivePrompt,
    GradeTestPrompt,
    PlanInteractivesPrompt,
    PlanLessonPrompt,
    PlanPrerequisitesPrompt,
    RuntimeRepairPrompt,
    StudyMaterialPrompt,
    WritePagePrompt,
    WriteQuestionsPrompt,
    WriteQuizQuestionsPrompt,
)
from graph.questions import LessonTestBlueprint, MarksPolicy, QuestionFinisher, QuizBlueprint
from graph.sandbox import SandboxRunner
from graph.schemas import (
    MATERIAL_SCHEMAS,
    AlignmentReport,
    DiagnosticBundle,
    GradeReport,
    InteractiveComponent,
    InteractivePlan,
    LearnerAssessment,
    LessonPlan,
    PageContent,
    PrerequisiteList,
    QuestionBatch,
)
from graph.shapes import LessonShapes
from graph.validators import (
    DiagnosticValidator,
    GradeReportValidator,
    InteractivePlanValidator,
    PageValidator,
    PlanValidator,
    PrerequisiteListValidator,
    QuestionBatchValidator,
    StudyMaterialValidator,
)
from llm_registry.gateway import AllModelsFailed, Gateway
from llm_registry.models import LLMModel, ModelCall, NodeConfig, NodeModelBinding, Provider
from llm_registry.node_configs import NodeConfigSync
from llm_registry.resolver import RegistryResolver
from quizzes.traits import GatewayTopicTraits

pytestmark = pytest.mark.django_db


@pytest.fixture
def server():
    with FakeLLMServer() as running:
        yield running


def bind_fake(server, method: str, monkeypatch) -> dict:
    monkeypatch.setenv("FAKE_LLM_API_KEY", "not-a-secret")
    NodeConfigSync().ensure()
    provider = Provider.objects.create(
        key="fake", kind="openai_compatible", api_key_env="FAKE_LLM_API_KEY", base_url=server.base_url
    )
    model = LLMModel.objects.create(
        provider=provider,
        name="fake-model",
        supports_structured_output=True,
        structured_output_method=method,
        supports_tool_calling=True,
        context_window=1_000_000,
        max_output_tokens=65_536,
    )
    for node in NodeConfig.objects.all():
        NodeModelBinding.objects.create(node=node, model=model, priority=0)
    return RegistryResolver().snapshot().to_json()


STATE = {"topic": "Binary search", "settings": {}, "profile": {}}


@pytest.mark.parametrize("method", ["json_schema", "function_calling"])
def test_a_structured_call_returns_a_valid_bundle_and_is_logged(server, monkeypatch, method):
    snapshot = bind_fake(server, method, monkeypatch)
    messages = DiagnosticPrompt().messages(STATE)

    result = Gateway().invoke("diagnostic.generate", messages, snapshot=snapshot, schema=DiagnosticBundle)

    assert isinstance(result.output, DiagnosticBundle)
    assert len(result.output.diagnostic) == 10 and "Binary search" in result.output.diagnostic[0].concept
    call = ModelCall.objects.get(node_key="diagnostic.generate")
    assert call.status == "ok" and call.output_tokens > 0


def test_a_schema_the_fake_does_not_know_fails_every_model(server, monkeypatch):
    class Unknown(BaseModel):
        x: int

    snapshot = bind_fake(server, "json_schema", monkeypatch)

    with pytest.raises(AllModelsFailed, match="no canned output"):
        Gateway(sleep=lambda s: None).invoke("learner.assess", [], snapshot=snapshot, schema=Unknown)


def test_the_prerequisite_list_is_served_valid_and_named_for_the_topic(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    state = make_state() | {"assessment": make_assessment() | {"level": "beginner"}}

    result = Gateway().invoke(
        "prerequisites.plan", PlanPrerequisitesPrompt().messages(state), snapshot=snapshot, schema=PrerequisiteList
    )

    listed = result.output.model_dump(mode="json")
    assert PrerequisiteListValidator().validate(listed, topic="Binary search") == []
    assert all("Binary search" in item["name"] for item in listed["prerequisites"])


def test_a_plan_for_a_beginner_teaches_the_planned_prerequisites_on_the_introduction_page(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    planned = [{"name": "Counting", "why_needed": "x"}, {"name": "Ordering", "why_needed": "y"}]
    state = make_state() | {"assessment": make_assessment() | {"level": "beginner"}, "prerequisites_to_cover": planned}

    plan = Gateway().invoke("lesson.plan", PlanLessonPrompt().messages(state), snapshot=snapshot, schema=LessonPlan)

    document = LevelScheme.stamp(plan.output.model_dump(mode="json") | {"level": "beginner"})
    problems = PlanValidator().validate(
        document, prerequisites_to_cover=planned, shape=LessonShapes.for_level(Level.BEGINNER)
    )
    assert problems == []


def test_the_assessment_schema_is_served(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)

    result = Gateway().invoke("learner.assess", DiagnosticPrompt().messages(STATE), snapshot=snapshot,
                              schema=LearnerAssessment)  # fmt: skip

    assert result.output.level == "proficient"


@pytest.mark.parametrize("kind", ["cheat_sheet", "revision_sheet", "practice_sheet"])
def test_a_study_sheet_is_valid_and_covers_the_concepts_in_the_prompt(server, monkeypatch, kind):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    concepts = ["Halving the range", "Time complexity", "Loop invariants"]
    state = STATE | {"kind": kind, "concepts": concepts}

    result = Gateway().invoke("study.generate", StudyMaterialPrompt().messages(state), snapshot=snapshot,
                              schema=MATERIAL_SCHEMAS[kind])  # fmt: skip

    content = result.output.model_dump(mode="json")
    if kind == "practice_sheet":  # the graph sets marks and computes answers before the validator sees the questions
        content["questions"], problems = QuestionFinisher().finish(content["questions"])
        assert problems == []
    assert StudyMaterialValidator().validate(content, kind=kind, concepts=concepts) == []


# --- Stage B -----------------------------------------------------------------------------------------------------


def stage_b_state(topic="Binary search"):
    required = [{"name": "Arrays", "why_needed": "x"}]
    return make_state(topic=topic, prerequisites_to_cover=required)


def call(snapshot, node, schema, prompt):
    return Gateway().invoke(node, prompt, snapshot=snapshot, schema=schema).output.model_dump(mode="json")


def test_the_plan_the_page_and_the_test_pass_the_real_validators(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    state = stage_b_state()

    plan = call(snapshot, "lesson.plan", LessonPlan, PlanLessonPrompt().messages(state))
    assert PlanValidator().validate(plan, prerequisites_to_cover=[{"name": "Arrays"}]) == []
    assert plan["quantitative"] is True and "final_test" not in plan

    state = state | {"plan": plan}
    page_plan = plan["pages"][1]
    page = call(snapshot, "page.generate", PageContent, WritePagePrompt().messages(state | {"page_plan": page_plan}))
    assert PageValidator().validate(page, plan_page=page_plan) == [] and page["key"] == "core"

    cells = LessonTestBlueprint.for_topic(plan["quantitative"]).cells
    batch = {"id": "b1-1", "cells": [c.as_dict() for c in cells]}
    asked = ["An earlier question?"]
    test = call(
        snapshot, "test.generate", QuestionBatch,
        WriteQuestionsPrompt().messages(state | {"batch": batch, "exclusions": asked}),
    )  # fmt: skip
    for cell, question in zip(cells, test["questions"], strict=True):
        question["id"] = cell.question_id
    questions, finishing = QuestionFinisher().finish(test["questions"])
    assert finishing == []
    assert {q["type"] for q in questions} >= {"msq", "numerical"}  # the canned lesson has the new kinds
    assert all(q["marks"] == MarksPolicy.marks(q["type"], q["difficulty"]) for q in questions)
    assert sum(q["marks"] for q in questions) == 20
    assert QuestionBatchValidator().validate(questions, cells=cells) == []

    # the same cells asked again after ten questions were asked give other questions
    again = call(
        snapshot, "test.generate", QuestionBatch,
        WriteQuestionsPrompt().messages(state | {"batch": batch, "exclusions": [q["question"] for q in questions]}),
    )  # fmt: skip
    assert {q["question"] for q in again["questions"]}.isdisjoint(q["question"] for q in questions)


@pytest.mark.parametrize(("topic", "first_kind"), [("Binary search", "svg_diagram"), ("Asexual reproduction", "image")])
def test_the_interactive_plan_passes_the_validator_and_follows_the_topic(server, monkeypatch, topic, first_kind):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    state = stage_b_state(topic)

    plan = call(snapshot, "interactive.plan", InteractivePlan, PlanInteractivesPrompt().messages(state))

    assert InteractivePlanValidator().validate(plan, pages=state["pages"], settings=state["settings"]) == []
    assert plan["specs"][0]["kind"] == first_kind


@pytest.mark.skipif(not SandboxRunner().available(), reason="the sandbox package is not installed")
@pytest.mark.parametrize("kind", ["simulation", "interactive_graph", "svg_diagram"])
def test_each_kind_of_widget_code_passes_the_real_sandbox_check(server, monkeypatch, kind):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    state = stage_b_state()
    spec = state["interactive_plan"]["specs"][0] | {"kind": kind, "id": "demo"}
    subject = state | {
        "spec": spec,
        "component_name": "Interactive_demo",
        "section": state["pages"]["introduction"]["sections"][0],
    }

    component = call(
        snapshot, "interactive.generate", InteractiveComponent, GenerateInteractivePrompt().messages(subject)
    )
    check = SandboxRunner().check_code(component["tsx"], required=["Interactive_demo"])

    assert check.errors == [] and component["component_name"] == "Interactive_demo"


def test_the_alignment_report_is_valid_and_passes(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)

    report = call(snapshot, "alignment.judge", AlignmentReport, AlignmentPrompt().messages(stage_b_state()))

    assert AlignmentReport(**report).recompute_passed(3) is True


def compile_subject():
    state = stage_b_state()
    components = [{"name": "Interactive_demo", "anchor": "s1", "purpose": "shows halving"}]
    return state | {"key": "core", "components": components, "figures": []}


@pytest.mark.skipif(not SandboxRunner().available(), reason="the sandbox package is not installed")
def test_a_compiled_page_comes_back_as_text_with_the_widget_placed_and_passes_the_real_check(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    messages = CompilePagePrompt().messages(compile_subject())

    code = Gateway().invoke("page.compile", messages, snapshot=snapshot).output

    assert 'section.id === "s1" ? (<><Interactive_demo /></>)' in code and "LESSON.pages.core" in code
    assert SandboxRunner().check_code(code, required=["Page_core"], components=["Interactive_demo"]).errors == []


@pytest.mark.skipif(not SandboxRunner().available(), reason="the sandbox package is not installed")
def test_a_crashed_interactive_is_replaced_by_code_that_passes_the_real_check(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    subject = {
        "code": "function Interactive_demo() { throw new Error('boom'); }",
        "error": {"message": "Interactive_demo crashed: boom"},
        "contract": DocumentAssembler().component_contract("Interactive_demo"),
    }

    code = Gateway().invoke("runtime.repair", RuntimeRepairPrompt().messages(subject), snapshot=snapshot).output

    assert "boom" not in code
    assert SandboxRunner().check_code(code, required=["Interactive_demo"]).errors == []


def test_a_grading_prompt_gets_one_valid_grade_per_question(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    items = [
        {
            "id": "t7",
            "type": "short_answer",
            "marks": 3,
            "question": "Why?",
            "answer": "Because.",
            "criteria": [{"text": "names it", "marks": 1}, {"text": "explains it", "marks": 2}],
        },
        {
            "id": "t9",
            "type": "long_answer",
            "marks": 5,
            "question": "Write it",
            "answer": "def search(items, t):\n    return 0" * 2,
            "criteria": [{"text": "states it", "marks": 3}, {"text": "shows it", "marks": 2}],
        },
    ]
    messages = GradeTestPrompt().messages({"topic": "Binary search", "items": items, "profile": {}})

    report = call(snapshot, "test.grade", GradeReport, messages)

    assert [(g["question_id"], g["awards"]) for g in report["grades"]] == [("t7", [0, 1]), ("t9", [3, 2])]
    assert GradeReportValidator().validate(report, questions=items) == []


def test_a_text_prompt_the_fake_does_not_know_fails_every_model(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)

    with pytest.raises(AllModelsFailed, match="no canned text output"):
        Gateway(sleep=lambda s: None).invoke("code.repair", [{"role": "user", "content": "x"}], snapshot=snapshot)


def test_the_media_agent_finds_downloads_and_stores_a_picture_end_to_end(server, monkeypatch, settings, tmp_path):
    base = server.base_url.removesuffix("/v1")
    settings.WIKIMEDIA_API_URL = f"{base}/w/api.php"
    settings.MEDIA_ALLOW_PRIVATE_HOSTS = True
    settings.MEDIA_ROOT = tmp_path
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    state = stage_b_state("Asexual reproduction") | {
        "snapshot": snapshot,
        "settings": {"media_sources": ["wikimedia"], "allowed_media_licenses": ["cc0", "cc-by-sa"]},
    }
    spec = {"id": "amoeba", "page": "introduction", "anchor_section": "s1", "kind": "image", "purpose": "p" * 20,
            "description": "An amoeba dividing", "media_query": "amoeba"}  # fmt: skip
    ctx = FlowContext(gateway=Gateway(), media=MediaLibrary.default(), events=lambda event: None)

    ref = MediaFinder().find(ctx, state, spec)

    assert ref["kind"] == "image" and ref["license"] == "cc-by-sa" and ref["attribution"] == "Fake Photographer"
    assert (tmp_path / ref["file"]).read_bytes()[:4] == b"\x89PNG" and re.fullmatch(r"[0-9a-f-]{36}", ref["asset_id"])
    assert ModelCall.objects.filter(node_key="media.search", status="ok").count() == 2  # the search, then the submit


@pytest.mark.parametrize(
    ("topic", "quantitative", "programming"),
    [
        ("Solving quadratic equations", True, False),
        ("Python loops", False, True),
        ("The French revolution", False, False),
    ],
)
def test_the_topic_judge_calls_calculation_and_programming_topics_by_their_words(
    server, monkeypatch, topic, quantitative, programming
):
    bind_fake(server, "json_schema", monkeypatch)

    traits = GatewayTopicTraits().judge(topic)

    assert (traits.quantitative, traits.programming) == (quantitative, programming)


def test_the_calibration_pool_is_a_bundle_the_pool_rules_accept(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    state = STATE | {"settings": {"diagnostic_questions_per_band": 2}, "include_prerequisites": False}

    result = Gateway().invoke(
        "diagnostic.generate", DiagnosticPrompt().messages(state), snapshot=snapshot, schema=DiagnosticBundle
    )

    bundle = result.output.model_dump(mode="json")
    assert DiagnosticValidator().validate(bundle, settings=state["settings"], include_prerequisites=False) == []


def test_a_quizs_questions_come_back_one_for_each_cell_and_pass_the_real_batch_validator(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    blueprint = QuizBlueprint.for_topic(5, ("mcq", "msq"), Level.FOUNDATION)
    batch = {"id": "b1-1", "cells": [cell.as_dict() for cell in blueprint.cells]}
    quiz = {"level": "foundation", "code_format": False, "sources": {}}
    messages = WriteQuizQuestionsPrompt().messages(STATE | {"batch": batch, "quiz": quiz, "exclusions": []})

    result = Gateway().invoke("test.generate", messages, snapshot=snapshot, schema=QuestionBatch)

    written = [q.model_dump(mode="json") for q in result.output.questions]
    for cell, question in zip(blueprint.cells, written, strict=True):
        question["id"] = cell.question_id
    finished, finishing = QuestionFinisher().finish(written)
    assert finishing == [] and QuestionBatchValidator().validate(finished, cells=blueprint.cells) == []

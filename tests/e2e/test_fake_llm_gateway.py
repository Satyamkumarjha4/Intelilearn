"""Unit under test: the real `Gateway` and LangChain client driven against `tests/e2e/fake_llm_server.py`.

Why: every other test fakes the chat model, so none proves that the gateway's real request (structured output through
a real OpenAI-compatible client, the registry's parameters, token logging) is understood and answered correctly over
HTTP. This does, offline, and it validates the fake that the browser walk-through relies on.

Use cases:
- a structured-output call (json_schema) returns a valid DiagnosticBundle, and the call is logged with tokens
- a function-calling model gets the same bundle through a tool call
- the three study sheets come back valid and pass the study validator for the concepts in the prompt
- every Stage B output (plan, page, test, interactive plan, alignment report) passes the real validators, and each kind
  of widget code passes the real sandbox check
- the media agent finds, downloads and stores a picture end to end: real gateway and client, real library and
  downloader, the fake's Wikimedia API and image
- a page compiled through the text path (no schema) keeps every section and places the widgets, and passes the real
  sandbox check
- a crashed interactive is answered with a replacement that passes the real sandbox check
- a text prompt the fake does not know is refused
- a schema the fake does not know is refused, and the gateway reports every model failed
"""

import re

import pytest
from e2e.fake_llm_server import FakeLLMServer
from pydantic import BaseModel
from support.lesson_data import make_state

from graph.codegen import DocumentAssembler
from graph.context import FlowContext
from graph.media import MediaLibrary
from graph.nodes.media_agent import MediaFinder
from graph.prompts import (
    AlignmentPrompt,
    CompilePagePrompt,
    DiagnosticPrompt,
    GenerateInteractivePrompt,
    PlanInteractivesPrompt,
    PlanLessonPrompt,
    RuntimeRepairPrompt,
    StudyMaterialPrompt,
    WritePagePrompt,
    WriteTestPrompt,
)
from graph.sandbox import SandboxRunner
from graph.schemas import (
    MATERIAL_SCHEMAS,
    AlignmentReport,
    DiagnosticBundle,
    FinalTest,
    InteractiveComponent,
    InteractivePlan,
    LearnerAssessment,
    LessonPlan,
    PageContent,
)
from graph.validators import (
    FinalTestValidator,
    InteractivePlanValidator,
    PageValidator,
    PlanValidator,
    StudyMaterialValidator,
)
from llm_registry.gateway import AllModelsFailed, Gateway
from llm_registry.models import LLMModel, ModelCall, NodeConfig, NodeModelBinding, Provider
from llm_registry.node_configs import NodeConfigSync
from llm_registry.resolver import RegistryResolver

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


def test_the_assessment_schema_is_served(server, monkeypatch):
    snapshot = bind_fake(server, "json_schema", monkeypatch)

    result = Gateway().invoke("learner.assess", DiagnosticPrompt().messages(STATE), snapshot=snapshot,
                              schema=LearnerAssessment)  # fmt: skip

    assert result.output.level == "intermediate"


@pytest.mark.parametrize("kind", ["cheat_sheet", "revision_sheet", "practice_sheet"])
def test_a_study_sheet_is_valid_and_covers_the_concepts_in_the_prompt(server, monkeypatch, kind):
    snapshot = bind_fake(server, "json_schema", monkeypatch)
    concepts = ["Halving the range", "Time complexity", "Loop invariants"]
    state = STATE | {"kind": kind, "concepts": concepts}

    result = Gateway().invoke("study.generate", StudyMaterialPrompt().messages(state), snapshot=snapshot,
                              schema=MATERIAL_SCHEMAS[kind])  # fmt: skip

    content = result.output.model_dump(mode="json")
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
    assert PlanValidator().validate(plan, settings=state["settings"], prerequisites_to_cover=[{"name": "Arrays"}]) == []

    state = state | {"plan": plan}
    page_plan = plan["pages"][1]
    page = call(snapshot, "page.generate", PageContent, WritePagePrompt().messages(state | {"page_plan": page_plan}))
    assert PageValidator().validate(page, plan_page=page_plan) == [] and page["key"] == "core"

    test = call(snapshot, "test.generate", FinalTest, WriteTestPrompt().messages(state))
    assert FinalTestValidator().validate(test, spec=plan["final_test"]) == []


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

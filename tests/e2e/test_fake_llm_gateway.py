"""Unit under test: the real `Gateway` and LangChain client driven against `tests/e2e/fake_llm_server.py`.

Why: every other test fakes the chat model, so none proves that the gateway's real request (structured output through
a real OpenAI-compatible client, the registry's parameters, token logging) is understood and answered correctly over
HTTP. This does, offline, and it validates the fake that the browser walk-through relies on.

Use cases:
- a structured-output call (json_schema) returns a valid DiagnosticBundle, and the call is logged with tokens
- a function-calling model gets the same bundle through a tool call
- the three study sheets come back valid and pass the study validator for the concepts in the prompt
- a schema the fake does not know is refused, and the gateway reports every model failed
"""

import pytest
from e2e.fake_llm_server import FakeLLMServer
from pydantic import BaseModel

from graph.prompts import DiagnosticPrompt, StudyMaterialPrompt
from graph.schemas import MATERIAL_SCHEMAS, DiagnosticBundle, LearnerAssessment
from graph.validators import StudyMaterialValidator
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

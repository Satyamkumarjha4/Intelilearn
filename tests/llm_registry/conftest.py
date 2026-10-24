from dataclasses import asdict

import pytest

from llm_registry.models import LLMModel, NodeConfig, NodeModelBinding, Provider
from llm_registry.resolver import ResolvedModel, ResolvedNode
from llm_registry.signals import ensure_node_configs


@pytest.fixture
def node_configs(db):
    ensure_node_configs()
    return {n.node_key: n for n in NodeConfig.objects.all()}


@pytest.fixture
def gemini(db):
    return Provider.objects.create(key="gemini", kind="google_genai", api_key_env="GEMINI_API_KEY")


@pytest.fixture
def groq(db):
    return Provider.objects.create(key="groq", kind="groq", api_key_env="GROQ_API_KEY")


@pytest.fixture
def flash(gemini):
    return LLMModel.objects.create(
        provider=gemini,
        name="gemini-flash",
        default_params={"temperature": 0.5, "max_tokens": 8192},
        supports_structured_output=True,
        supports_tool_calling=True,
        supports_vision=True,
        supports_reasoning=True,
        reasoning_control="budget_tokens",
        context_window=1_000_000,
        max_output_tokens=65_536,
    )


@pytest.fixture
def llama(groq):
    return LLMModel.objects.create(
        provider=groq,
        name="llama",
        default_params={"temperature": 0.3},
        supports_structured_output=True,
        structured_output_method="function_calling",
        supports_tool_calling=True,
        context_window=131_072,
        max_output_tokens=32_768,
    )


@pytest.fixture
def bind(node_configs):
    def _bind(node_key, model, priority=0, **extra):
        return NodeModelBinding.objects.create(node=node_configs[node_key], model=model, priority=priority, **extra)

    return _bind


def resolved_model(name="primary", **overrides) -> ResolvedModel:
    values = dict(
        provider_key="fake",
        provider_kind="openai",
        model_name=name,
        params={},
        reasoning={},
        reasoning_effort="none",
        structured_output_method="json_schema",
        api_key_env="",
        base_url="",
        max_retries=2,
    )
    return ResolvedModel(**{**values, **overrides})


def make_snapshot(node_key: str, output: str, chain: list[ResolvedModel], enabled=True) -> dict:
    node = ResolvedNode(node_key, enabled, output, max_attempts=2, max_tool_steps=None, timeout_s=30, chain=chain)
    return {"version": 1, "nodes": {node_key: asdict(node)}}


class FakeChat:
    """Scripted stand-in for a LangChain chat model: each invoke pops the next item (raising it if it's an error)."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[list] = []
        self.structured = None
        self.tools = None

    def with_structured_output(self, schema, method=None, include_raw=False):
        self.structured = (schema, method, include_raw)
        return self

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# Test modules can't import from conftest (importlib mode), so the helpers are served as fixtures.
@pytest.fixture(name="FakeChat")
def _fake_chat_class():
    return FakeChat


@pytest.fixture(name="make_snapshot")
def _make_snapshot():
    return make_snapshot


@pytest.fixture(name="resolved_model")
def _resolved_model():
    return resolved_model

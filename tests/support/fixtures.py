"""Fixtures for tests that run graph nodes or the runner (registered for every test through tests/conftest.py).

- `flow_settings`: the default FlowSettings snapshot, as stored on a lesson.
- `valid_bundle`: a DiagnosticBundle dump that passes `DiagnosticValidator` with the default settings.
- `gateway` (`FakeGateway`), `sandbox` (`FakeSandbox`), `events` (`ListEvents`), `ctx` (a `FlowContext` made of them)
  and `runtime` (what LangGraph passes a node): the doubles a node test needs.
- `lesson_state`: the state `load_context` would produce for `lesson`.
- `make_snapshot_for_nodes(disabled=..., attempts=...)`: a registry snapshot where every node has a model chain.
"""

from types import SimpleNamespace
from typing import ClassVar

import pytest

from graph.context import FlowContext

from .fakes import FakeGateway, FakeSandbox, ListEvents
from .quiz_data import DEFAULT_SETTINGS, make_prerequisites, make_questions


@pytest.fixture
def flow_settings() -> dict:
    return dict(DEFAULT_SETTINGS)


@pytest.fixture
def valid_bundle() -> dict:
    prerequisites, prerequisite_questions = make_prerequisites()
    return {
        "diagnostic": make_questions(),
        "prerequisites": prerequisites,
        "prerequisite_questions": prerequisite_questions,
    }


# --- nodes and graphs ---------------------------------------------------------------------------------------------


def budget_snapshot(*, disabled: tuple[str, ...] = ("diagnostic.review", "media.verify"), attempts: int = 2) -> dict:
    """A registry snapshot where every node has a model chain, so each is enabled with `attempts` attempts.

    The optional judges are off unless a test turns them on, as in a registry nobody has bound them in."""
    from llm_registry.node_specs import NODE_SPECS

    chain = [{"model_name": "fake"}]
    nodes = {
        spec.key: {
            "enabled": True,
            "max_attempts": attempts,
            "max_tool_steps": 6,
            "chain": [] if spec.key in disabled else chain,
        }
        for spec in NODE_SPECS.required() + NODE_SPECS.optional()
    }
    return {"version": 1, "nodes": nodes}


@pytest.fixture
def make_snapshot_for_nodes():
    return budget_snapshot


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def events():
    return ListEvents()


@pytest.fixture
def sandbox():
    return FakeSandbox()


@pytest.fixture
def ctx(gateway, sandbox, events):
    return FlowContext(gateway=gateway, sandbox=sandbox, events=events, run_id="run-1")


@pytest.fixture
def runtime(ctx):
    """What LangGraph passes a node besides the state."""
    return SimpleNamespace(context=ctx)


@pytest.fixture
def lesson_state(lesson, flow_settings):
    """The state `load_context` would produce for `lesson`."""
    return {
        "lesson_id": str(lesson.id),
        "topic": lesson.topic,
        "user_context": "",
        "profile": {"education_level": "Undergraduate", "preferred_language": "en"},
        "snapshot": budget_snapshot(),
        "settings": flow_settings,
    }


# --- the lessons API ------------------------------------------------------------------------------------------


class RecordingQueue:
    """Stands in for Celery: remembers which runs were enqueued (class-wide, so the API's own instance shares it)."""

    runs: ClassVar[list] = []

    def enqueue(self, run) -> None:
        type(self).runs.append(run)


@pytest.fixture
def queue(settings):
    """A recording queue, also installed as the API's task queue."""
    RecordingQueue.runs = []
    settings.LESSON_TASK_QUEUE = "support.fixtures.RecordingQueue"
    return RecordingQueue()


@pytest.fixture
def bound_registry(db):
    """A registry where every required node has a model, so a lesson can be started."""
    from llm_registry.models import LLMModel, NodeConfig, NodeModelBinding, Provider
    from llm_registry.node_configs import NodeConfigSync

    NodeConfigSync().ensure()
    provider = Provider.objects.create(key="fake", kind="openai", api_key_env="OPENAI_API_KEY")
    model = LLMModel.objects.create(
        provider=provider,
        name="fake-model",
        supports_structured_output=True,
        supports_tool_calling=True,
        supports_vision=True,
        supports_reasoning=True,
        context_window=1_000_000,
        max_output_tokens=65_536,
    )
    for node in NodeConfig.objects.exclude(node_key__in=["diagnostic.review", "media.verify"]):
        NodeModelBinding.objects.create(node=node, model=model, priority=0)
    return model

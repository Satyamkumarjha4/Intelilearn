"""Fixtures shared by the graph tests.

- `flow_settings`: the default FlowSettings snapshot, as stored on a lesson.
- `valid_bundle`: a DiagnosticBundle dump that passes `DiagnosticValidator` with the default settings.
"""

import pytest
from support.quiz_data import DEFAULT_SETTINGS, make_prerequisites, make_questions


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

from types import SimpleNamespace  # noqa: E402

from support.fakes import FakeGateway, FakeSandbox, ListEvents  # noqa: E402

from graph.context import FlowContext  # noqa: E402


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

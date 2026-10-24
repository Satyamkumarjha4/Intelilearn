"""Unit under test: `llm_registry.node_specs`, the NodeSpecCatalog of every LLM step the graph runs and what each
needs (capabilities, output mode, minimum output and context).

Why: the specs decide which models the admin may bind to a node. A missing or wrong requirement lets a model without
tool calling or vision be bound, and the lesson fails mid-flow instead of at configuration time.

Use cases:
- every node documented in model-registry.md has a spec
- only the quiz reviewer and the vision check are optional; every other node is required
- tool calling, vision, text output and the alignment judge's context are declared
- every structured node requires structured output
- an unknown node key is a clear error that says how to add one
"""

import pytest

from llm_registry.node_specs import NODE_SPECS, Capability, OutputMode

DOCUMENTED_NODES = {
    "diagnostic.generate", "diagnostic.review", "learner.assess", "study.generate", "lesson.plan", "page.generate",
    "test.generate", "interactive.plan", "media.search", "media.verify", "interactive.generate", "alignment.judge",
    "page.compile", "code.repair", "runtime.repair", "test.grade",
}  # fmt: skip


def test_every_documented_node_has_a_spec():
    assert set(NODE_SPECS) == DOCUMENTED_NODES


def test_only_judges_and_vision_check_are_optional():
    assert {s.key for s in NODE_SPECS.optional()} == {"diagnostic.review", "media.verify"}
    assert len(NODE_SPECS.required()) == len(NODE_SPECS) - 2


def test_capability_requirements():
    assert NODE_SPECS["media.search"].requires == {Capability.TOOL_CALLING}
    assert NODE_SPECS["media.search"].output == OutputMode.TOOLS
    assert Capability.VISION in NODE_SPECS["media.verify"].requires
    assert NODE_SPECS["page.compile"].output == OutputMode.TEXT
    assert NODE_SPECS["alignment.judge"].min_context >= 64_000


def test_structured_nodes_require_structured_output():
    for spec in NODE_SPECS.values():
        if spec.output == OutputMode.STRUCTURED:
            assert Capability.STRUCTURED_OUTPUT in spec.requires, spec.key


def test_unknown_node_is_a_clear_error():
    with pytest.raises(KeyError, match="add a NodeSpec"):
        NODE_SPECS["nope.generate"]

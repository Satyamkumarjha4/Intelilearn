import pytest

from llm_registry.node_specs import NODE_SPECS, Capability, OutputMode, get_spec

DOCUMENTED_NODES = {
    "diagnostic.generate", "diagnostic.review", "learner.assess", "study.generate", "lesson.plan", "page.generate",
    "test.generate", "interactive.plan", "media.search", "media.verify", "interactive.generate", "alignment.judge",
    "page.compile", "code.repair", "runtime.repair", "test.grade",
}  # fmt: skip


def test_every_documented_node_has_a_spec():
    assert set(NODE_SPECS) == DOCUMENTED_NODES


def test_only_judges_and_vision_check_are_optional():
    assert {k for k, s in NODE_SPECS.items() if s.optional} == {"diagnostic.review", "media.verify"}


def test_capability_requirements():
    assert get_spec("media.search").requires == {Capability.TOOL_CALLING}
    assert get_spec("media.search").output == OutputMode.TOOLS
    assert Capability.VISION in get_spec("media.verify").requires
    assert get_spec("page.compile").output == OutputMode.TEXT
    assert get_spec("alignment.judge").min_context >= 64_000


def test_structured_nodes_require_structured_output():
    for spec in NODE_SPECS.values():
        if spec.output == OutputMode.STRUCTURED:
            assert Capability.STRUCTURED_OUTPUT in spec.requires, spec.key


def test_unknown_node_is_a_clear_error():
    with pytest.raises(KeyError, match="add a NodeSpec"):
        get_spec("nope.generate")

import json

import pytest

from llm_registry.resolver import node_from_snapshot, registry_snapshot, resolve_registry

pytestmark = pytest.mark.django_db


def test_params_merge_model_then_node_then_binding(node_configs, llama, bind):
    node = node_configs["learner.assess"]
    node.params_override = {"temperature": 0.1, "max_tokens": 500}
    node.save()
    bind("learner.assess", llama, params_override={"max_tokens": 900})

    model = resolve_registry()["learner.assess"].chain[0]

    assert model.params == {"temperature": 0.1, "max_tokens": 900}


def test_chain_is_ordered_and_skips_disabled(node_configs, flash, llama, bind):
    bind("learner.assess", llama, priority=1)
    bind("learner.assess", flash, priority=0)

    assert [m.model_name for m in resolve_registry()["learner.assess"].chain] == ["gemini-flash", "llama"]

    flash.provider.is_enabled = False
    flash.provider.save()
    assert [m.model_name for m in resolve_registry()["learner.assess"].chain] == ["llama"]


def test_invalid_binding_is_skipped(node_configs, llama, bind):
    bind("learner.assess", llama)
    llama.supports_structured_output = False  # model edited after binding
    llama.save()

    assert resolve_registry()["learner.assess"].chain == []


def test_reasoning_precedence_and_translation(node_configs, flash, bind):
    node = node_configs["lesson.plan"]  # spec default: high
    bind("lesson.plan", flash)
    assert resolve_registry()["lesson.plan"].chain[0].reasoning == {"thinking_budget": 24576}

    node.reasoning_effort = "low"
    node.save()
    assert resolve_registry()["lesson.plan"].chain[0].reasoning == {"thinking_budget": 2048}

    binding = node.bindings.get()
    binding.reasoning_effort = "none"
    binding.save()
    assert resolve_registry()["lesson.plan"].chain[0].reasoning == {}


def test_non_reasoning_model_gets_no_reasoning(node_configs, llama, bind):
    bind("lesson.plan", llama)
    model = resolve_registry()["lesson.plan"].chain[0]
    assert model.reasoning == {}
    assert model.reasoning_effort == "none"


def test_cache_is_cleared_when_the_registry_changes(node_configs, flash, llama, bind):
    bind("learner.assess", flash)
    assert resolve_registry()["learner.assess"].chain[0].model_name == "gemini-flash"

    bind("learner.assess", llama, priority=1)

    assert len(resolve_registry()["learner.assess"].chain) == 2


def test_snapshot_is_json_and_round_trips(node_configs, flash, bind):
    bind("media.search", flash)
    snapshot = json.loads(json.dumps(registry_snapshot()))

    node = node_from_snapshot(snapshot, "media.search")

    assert node.output == "tools"
    assert node.max_tool_steps == 6
    assert node.chain[0].model_name == "gemini-flash"


def test_snapshot_is_frozen_against_later_edits(node_configs, flash, llama, bind):
    bind("learner.assess", flash)
    snapshot = json.loads(json.dumps(registry_snapshot()))
    node_configs["learner.assess"].bindings.all().delete()
    bind("learner.assess", llama)

    assert node_from_snapshot(snapshot, "learner.assess").chain[0].model_name == "gemini-flash"

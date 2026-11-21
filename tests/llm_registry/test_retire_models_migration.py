"""Unit under test: the data migration `0009_retire_models`, which takes the model ids the providers have stopped
serving (`gemini-3.5-flash`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.5-pro`,
`llama-3.3-70b-versatile`) out of the registry.

Why: model-strategy decision 9. `gemini-3.5-flash` is on none of Google's pages and drew 221 rate-limit errors in 532
recorded attempts; the Llama model returns 404 since Groq shut it down on 2026-08-16. Left in a chain they are tried
first, fail, and slow every call. But a node whose only layer was one of them must stay visible in the console, not
silently lose its row.

Use cases:
- a retired model that no node uses is deleted
- a retired model in a chain that has another layer is removed from the chain (the other layers keep their order) and
  deleted
- a retired model that is a node's only layer is kept, switched off and marked deprecated, with its binding, so the
  console and `manage.py check` show the node has no usable model
- a model that is not retired is never touched, and running it again changes nothing
"""

import importlib

import pytest
from django.apps import apps

from llm_registry.models import LLMModel, NodeModelBinding

pytestmark = pytest.mark.django_db


def retire():
    importlib.import_module("llm_registry.migrations.0009_retire_models").retire(apps, None)


def model(provider, name):
    return LLMModel.objects.create(
        provider=provider, name=name, supports_structured_output=True, context_window=1_000_000,
        max_output_tokens=65_536,
    )  # fmt: skip


def test_a_retired_model_no_node_uses_is_deleted(gemini, groq):
    model(gemini, "gemini-3.5-flash")
    model(gemini, "gemini-2.5-pro")
    model(groq, "llama-3.3-70b-versatile")
    keep = model(gemini, "gemini-3.6-flash")

    retire()

    assert list(LLMModel.objects.values_list("name", flat=True)) == [keep.name]


def test_a_retired_model_in_a_chain_with_another_layer_leaves_the_chain_and_is_deleted(
    node_configs, gemini, groq, bind
):
    old, lite, oss = model(gemini, "gemini-3.5-flash"), model(gemini, "gemini-3.5-flash-lite"), model(groq, "oss")
    bind("page.generate", old, priority=0)
    bind("page.generate", lite, priority=1)
    bind("test.generate", oss, priority=0)
    bind("test.generate", old, priority=1)

    retire()

    assert not LLMModel.objects.filter(name="gemini-3.5-flash").exists()
    chains = {}
    for b in NodeModelBinding.objects.order_by("node__node_key", "priority"):
        chains.setdefault(b.node.node_key, []).append((b.priority, b.model.name))
    assert chains == {"page.generate": [(1, "gemini-3.5-flash-lite")], "test.generate": [(0, "oss")]}


def test_a_retired_model_that_is_a_nodes_only_layer_is_kept_switched_off_and_marked_deprecated(
    node_configs, gemini, bind
):
    old = model(gemini, "gemini-3.5-flash")
    bind("page.generate", old)

    retire()

    old.refresh_from_db()
    assert (old.is_enabled, old.status) == (False, "deprecated")
    assert NodeModelBinding.objects.filter(node__node_key="page.generate", model=old).exists()


def test_a_model_that_is_not_retired_is_untouched_and_running_again_changes_nothing(node_configs, gemini, bind):
    lite = model(gemini, "gemini-3.5-flash-lite")
    bind("page.generate", lite)

    retire()
    retire()

    lite.refresh_from_db()
    assert (lite.is_enabled, lite.status, lite.shutdown_on) == (True, "stable", None)
    assert NodeModelBinding.objects.count() == 1

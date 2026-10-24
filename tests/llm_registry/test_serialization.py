"""Unit under test: `llm_registry.serialization.RegistrySerializer` (registry <-> versioned JSON) and
`llm_registry.seed.DefaultRegistry`, plus the `seed_registry` and `export_registry` commands built on them.

Why: this is how a tuned registry moves between machines and how a fresh install gets working models. A half-applied
or unvalidated import would leave nodes bound to models that can't serve them.

Use cases:
- the default seed is valid, binds every required node, and switches the optional quality checks on with models that
  can do them (the quiz reviewer, and a vision model for the picture check)
- export then import round-trips to the same JSON
- an invalid import rolls back everything
- seed_registry leaves an existing registry alone unless forced
- seed_registry loads an exported file
"""

import json

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from llm_registry.models import LLMModel, NodeConfig, NodeModelBinding, Provider
from llm_registry.resolver import RegistryResolver
from llm_registry.seed import DefaultRegistry
from llm_registry.serialization import RegistrySerializer

pytestmark = pytest.mark.django_db


def test_default_seed_is_valid_and_covers_every_required_node():
    RegistrySerializer().load(DefaultRegistry().build())

    resolved = RegistryResolver().resolve()
    for node in NodeConfig.objects.all():
        if node.is_enabled:
            assert resolved[node.node_key].chain, f"{node.node_key} has no usable model"
    for key, chain in {
        "diagnostic.review": ["gemini-2.5-flash", "llama-3.3-70b-versatile"],
        "media.verify": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    }.items():
        assert NodeConfig.objects.get(node_key=key).is_enabled
        assert [m.model_name for m in resolved[key].chain] == chain
    chain_names = [m.model_name for m in resolved["media.verify"].chain]
    assert all(m.supports_vision for m in LLMModel.objects.filter(name__in=chain_names))  # it reads the picture
    assert [m.model_name for m in resolved["lesson.plan"].chain] == ["gemini-2.5-pro", "gemini-2.5-flash"]


def test_export_then_import_round_trips():
    RegistrySerializer().load(DefaultRegistry().build())
    exported = json.loads(json.dumps(RegistrySerializer().export()))
    NodeModelBinding.objects.all().delete()
    LLMModel.objects.all().delete()
    Provider.objects.all().delete()

    RegistrySerializer().load(exported)

    assert json.loads(json.dumps(RegistrySerializer().export())) == exported


def test_invalid_import_rolls_back_everything():
    data = DefaultRegistry().build()
    data["nodes"][0]["bindings"].append({"provider": "groq", "model": "llama-3.3-70b-versatile", "priority": 9,
                                         "params_override": {"top_k": 3}})  # fmt: skip

    with pytest.raises(ValidationError, match="top_k"):
        RegistrySerializer().load(data)

    assert not Provider.objects.exists()


def test_seed_command_is_idempotent(capsys):
    call_command("seed_registry")
    count = NodeModelBinding.objects.count()

    call_command("seed_registry")

    assert NodeModelBinding.objects.count() == count
    assert "leaving it alone" in capsys.readouterr().out


def test_seed_command_loads_a_file(tmp_path):
    call_command("seed_registry")
    call_command("export_registry", output=tmp_path / "registry.json")
    NodeModelBinding.objects.all().delete()

    call_command("seed_registry", file=tmp_path / "registry.json")

    assert NodeModelBinding.objects.count() == 32

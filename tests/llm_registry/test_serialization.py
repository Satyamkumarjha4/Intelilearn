import json

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from llm_registry.models import LLMModel, NodeConfig, NodeModelBinding, Provider
from llm_registry.resolver import resolve_registry
from llm_registry.seed import default_registry
from llm_registry.serialization import export_registry, import_registry

pytestmark = pytest.mark.django_db


def test_default_seed_is_valid_and_covers_every_required_node():
    import_registry(default_registry())

    resolved = resolve_registry()
    for node in NodeConfig.objects.all():
        if node.is_enabled:
            assert resolved[node.node_key].chain, f"{node.node_key} has no usable model"
    assert not NodeConfig.objects.get(node_key="diagnostic.review").is_enabled
    assert [m.model_name for m in resolved["lesson.plan"].chain] == ["gemini-2.5-pro", "gemini-2.5-flash"]


def test_export_then_import_round_trips():
    import_registry(default_registry())
    exported = json.loads(json.dumps(export_registry()))
    NodeModelBinding.objects.all().delete()
    LLMModel.objects.all().delete()
    Provider.objects.all().delete()

    import_registry(exported)

    assert json.loads(json.dumps(export_registry())) == exported


def test_invalid_import_rolls_back_everything():
    data = default_registry()
    data["nodes"][0]["bindings"].append({"provider": "groq", "model": "llama-3.3-70b-versatile", "priority": 9,
                                         "params_override": {"top_k": 3}})  # fmt: skip

    with pytest.raises(ValidationError, match="top_k"):
        import_registry(data)

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

    assert NodeModelBinding.objects.count() == 30

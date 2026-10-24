"""Unit under test: `llm_registry.admin`, the registry's admin screens and the export action.

Why: the admin is where models are bound to nodes. A changelist that fails to render, or an export that returns the
wrong thing, blocks tuning the registry.

Use cases:
- each registry changelist renders, with the key and chain-health marks
- the node config page renders its bindings inline with their status
- "Export the whole registry as JSON" downloads the RegistrySerializer export
"""

import json

import pytest
from django.urls import reverse

from llm_registry.seed import DefaultRegistry
from llm_registry.serialization import RegistrySerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    RegistrySerializer().load(DefaultRegistry().build())


@pytest.mark.parametrize("model", ["provider", "llmmodel", "nodeconfig", "modelcall"])
def test_changelists_render(admin_client, seeded, model):
    response = admin_client.get(reverse(f"admin:llm_registry_{model}_changelist"))

    assert response.status_code == 200
    if model in ("provider", "nodeconfig"):
        assert "✘" in response.content.decode() or "✔" in response.content.decode()


def test_node_config_page_shows_its_bindings(admin_client, seeded):
    from llm_registry.models import NodeConfig

    node = NodeConfig.objects.get(node_key="lesson.plan")
    response = admin_client.get(reverse("admin:llm_registry_nodeconfig_change", args=[node.pk]))

    assert response.status_code == 200
    assert "gemini-2.5-pro" in response.content.decode()


def test_export_action_downloads_the_registry(admin_client, seeded):
    from llm_registry.models import Provider

    response = admin_client.post(
        reverse("admin:llm_registry_provider_changelist"),
        {"action": "export_json", "_selected_action": [p.pk for p in Provider.objects.all()]},
    )

    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="llm-registry.json"'
    assert json.loads(response.content) == RegistrySerializer().export()

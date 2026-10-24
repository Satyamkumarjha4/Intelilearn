"""Unit under test: `llm_registry.node_configs.NodeConfigSync`, which gives every NodeSpec its NodeConfig row
(run on post_migrate).

Why: adding a node is meant to be "add a NodeSpec, run migrate". A spec without a row can't be bound in the admin or
resolved, so its graph step would fail; an existing row must never be reset to the defaults.

Use cases:
- creates a row with the spec's defaults for every spec without one
- is idempotent and never resets an edited row
- clears the resolver cache when it created rows
"""

import pytest

from llm_registry.models import NodeConfig
from llm_registry.node_configs import NodeConfigSync
from llm_registry.node_specs import NODE_SPECS

pytestmark = pytest.mark.django_db


class RecordingResolver:
    def __init__(self):
        self.invalidations = 0

    def invalidate(self):
        self.invalidations += 1


def test_creates_a_row_with_the_spec_defaults_for_every_spec():
    NodeConfig.objects.all().delete()

    created = NodeConfigSync().ensure()

    assert created == len(NODE_SPECS)
    plan = NodeConfig.objects.get(node_key="lesson.plan")
    assert plan.reasoning_effort == NODE_SPECS["lesson.plan"].default_reasoning
    assert (
        NodeConfig.objects.get(node_key="media.search").max_tool_steps
        == NODE_SPECS["media.search"].default_max_tool_steps
    )


def test_is_idempotent_and_never_resets_an_edited_row():
    NodeConfigSync().ensure()
    NodeConfig.objects.filter(node_key="lesson.plan").update(reasoning_effort="low")

    assert NodeConfigSync().ensure() == 0
    assert NodeConfig.objects.get(node_key="lesson.plan").reasoning_effort == "low"


def test_clears_the_resolver_cache_only_when_rows_were_created():
    NodeConfig.objects.filter(node_key="test.grade").delete()
    resolver = RecordingResolver()

    NodeConfigSync(resolver=resolver).ensure()
    NodeConfigSync(resolver=resolver).ensure()

    assert resolver.invalidations == 1

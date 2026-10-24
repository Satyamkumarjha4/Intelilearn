from django.db.models.signals import post_delete, post_migrate, post_save
from django.dispatch import receiver

from . import resolver
from .models import LLMModel, NodeConfig, NodeModelBinding, Provider
from .node_specs import NODE_SPECS

REGISTRY_MODELS = (Provider, LLMModel, NodeConfig, NodeModelBinding)


def _invalidate(sender, **kwargs):
    resolver.invalidate()


for model in REGISTRY_MODELS:
    post_save.connect(_invalidate, sender=model, dispatch_uid=f"llm_registry_save_{model.__name__}")
    post_delete.connect(_invalidate, sender=model, dispatch_uid=f"llm_registry_delete_{model.__name__}")


def ensure_node_configs(using="default") -> int:
    """Create a NodeConfig for every NodeSpec that doesn't have one yet (with the spec's defaults)."""
    existing = set(NodeConfig.objects.using(using).values_list("node_key", flat=True))
    missing = [
        NodeConfig(
            node_key=spec.key,
            reasoning_effort=spec.default_reasoning,
            max_attempts=spec.default_max_attempts,
            max_tool_steps=spec.default_max_tool_steps,
        )
        for key, spec in NODE_SPECS.items()
        if key not in existing
    ]
    NodeConfig.objects.using(using).bulk_create(missing)
    if missing:
        resolver.invalidate()
    return len(missing)


@receiver(post_migrate, dispatch_uid="llm_registry_ensure_node_configs")
def _sync_node_configs(sender, app_config=None, using="default", **kwargs):
    # A new NodeSpec in code gets its NodeConfig row on the next migrate, without a data migration.
    if app_config is not None and app_config.label == "llm_registry":
        ensure_node_configs(using)

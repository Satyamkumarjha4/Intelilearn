"""Signal receivers (Observer): thin hooks into RegistryResolver and NodeConfigSync."""

from django.db.models.signals import post_delete, post_migrate, post_save
from django.dispatch import receiver

from .models import LLMModel, NodeConfig, NodeModelBinding, Provider
from .node_configs import NodeConfigSync
from .resolver import RegistryResolver

REGISTRY_MODELS = (Provider, LLMModel, NodeConfig, NodeModelBinding)


def _invalidate(sender, **kwargs):
    RegistryResolver().invalidate()


for model in REGISTRY_MODELS:
    post_save.connect(_invalidate, sender=model, dispatch_uid=f"llm_registry_save_{model.__name__}")
    post_delete.connect(_invalidate, sender=model, dispatch_uid=f"llm_registry_delete_{model.__name__}")


@receiver(post_migrate, dispatch_uid="llm_registry_ensure_node_configs")
def _sync_node_configs(sender, app_config=None, using="default", **kwargs):
    # A new NodeSpec in code gets its NodeConfig row on the next migrate, without a data migration.
    if app_config is not None and app_config.label == "llm_registry":
        NodeConfigSync().ensure(using)

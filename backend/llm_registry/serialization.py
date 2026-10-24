"""Export / import the registry as JSON, keyed by names (provider key, model name, node key) rather than ids,
so a tuned setup can be copied between machines."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import LLMModel, NodeConfig, NodeModelBinding, Provider
from .node_configs import NodeConfigSync


class RegistrySerializer:
    FORMAT_VERSION = 1

    PROVIDER_FIELDS = ["kind", "api_key_env", "base_url", "rpm_limit", "is_enabled"]
    MODEL_FIELDS = [
        "label", "default_params", "supports_structured_output", "structured_output_method", "supports_tool_calling",
        "supports_parallel_tool_calls", "supports_vision", "supports_reasoning", "reasoning_control",
        "reasoning_disables_sampling", "context_window", "max_output_tokens", "rpm_limit", "input_cost_per_mtok",
        "output_cost_per_mtok", "is_enabled",
    ]  # fmt: skip
    NODE_FIELDS = ["is_enabled", "reasoning_effort", "params_override", "max_attempts", "max_tool_steps", "timeout_s"]
    BINDING_FIELDS = ["priority", "params_override", "reasoning_effort", "max_retries", "is_enabled"]

    def export(self) -> dict:
        return {
            "format_version": self.FORMAT_VERSION,
            "providers": [
                {"key": p.key, **{f: getattr(p, f) for f in self.PROVIDER_FIELDS}} for p in Provider.objects.all()
            ],
            "models": [
                {
                    "provider": m.provider.key,
                    "name": m.name,
                    **{f: self._plain(getattr(m, f)) for f in self.MODEL_FIELDS},
                }
                for m in LLMModel.objects.select_related("provider")
            ],
            "nodes": [
                {
                    "node_key": n.node_key,
                    **{f: getattr(n, f) for f in self.NODE_FIELDS},
                    "bindings": [
                        {
                            "provider": b.model.provider.key,
                            "model": b.model.name,
                            **{f: getattr(b, f) for f in self.BINDING_FIELDS},
                        }
                        for b in n.bindings.select_related("model__provider").order_by("priority")
                    ],
                }
                for n in NodeConfig.objects.prefetch_related("bindings")
            ],
        }

    @transaction.atomic
    def load(self, data: dict, *, replace_bindings: bool = True) -> dict:
        """Create or update everything in `data`. Each node's bindings are replaced by the imported list.
        Every row is validated like an admin save; any error rolls the whole import back."""
        if data.get("format_version") != self.FORMAT_VERSION:
            raise ValidationError(
                f"Unsupported registry format {data.get('format_version')!r}; expected {self.FORMAT_VERSION}."
            )
        NodeConfigSync().ensure()
        counts = {"providers": 0, "models": 0, "nodes": 0, "bindings": 0}

        providers = {}
        for item in data.get("providers", []):
            provider = Provider.objects.filter(key=item["key"]).first() or Provider(key=item["key"])
            self._assign(provider, item, self.PROVIDER_FIELDS)
            providers[provider.key] = self._save(provider)
            counts["providers"] += 1

        for item in data.get("models", []):
            provider = providers.get(item["provider"]) or Provider.objects.get(key=item["provider"])
            model = LLMModel.objects.filter(provider=provider, name=item["name"]).first() or LLMModel(
                provider=provider, name=item["name"]
            )
            self._assign(model, item, self.MODEL_FIELDS)
            self._save(model)
            counts["models"] += 1

        for item in data.get("nodes", []):
            try:
                node = NodeConfig.objects.get(node_key=item["node_key"])
            except NodeConfig.DoesNotExist:
                raise ValidationError(f"Unknown node {item['node_key']!r}.") from None
            self._assign(node, item, self.NODE_FIELDS)
            self._save(node)
            counts["nodes"] += 1
            if "bindings" in item and replace_bindings:
                counts["bindings"] += self._replace_bindings(node, item["bindings"])
        return counts

    def _replace_bindings(self, node: NodeConfig, bindings: list[dict]) -> int:
        node.bindings.all().delete()
        for b in bindings:
            model = LLMModel.objects.get(provider__key=b["provider"], name=b["model"])
            binding = NodeModelBinding(node=node, model=model)
            self._assign(binding, b, self.BINDING_FIELDS)
            try:
                self._save(binding)
            except ValidationError as exc:
                raise ValidationError(f"{node.node_key} → {model}: {'; '.join(exc.messages)}") from exc
        return len(bindings)

    @staticmethod
    def _assign(instance, item: dict, fields: list[str]) -> None:
        for f in fields:
            if f in item:
                setattr(instance, f, item[f])

    @staticmethod
    def _save(instance):
        instance.full_clean()
        instance.save()
        return instance

    @staticmethod
    def _plain(value):
        return float(value) if isinstance(value, Decimal) else value

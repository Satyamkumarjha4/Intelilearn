"""Flatten the registry into plain, serialisable objects the gateway can use.

Precedence (lowest → highest):
    params:    LLMModel.default_params < NodeConfig.params_override < NodeModelBinding.params_override
    reasoning: NodeSpec.default_reasoning < NodeConfig.reasoning_effort < NodeModelBinding.reasoning_effort

RegistryResolver caches the result; any registry save clears the cache (see signals.py). Lessons store a
RegistrySnapshot of it (`RegistryResolver().snapshot().to_json()`) so admin edits never change a run that is
already in progress.
"""

import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

from django.core.cache import cache as default_cache

from .node_specs import NODE_SPECS, Effort, NodeSpecCatalog
from .profiles import PROVIDER_PROFILES, ProviderProfiles

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedModel:
    provider_key: str
    provider_kind: str
    model_name: str
    params: dict
    reasoning: dict  # integration kwargs, e.g. {"reasoning_effort": "high"}
    reasoning_effort: str
    structured_output_method: str
    api_key_env: str
    base_url: str
    max_retries: int
    provider_rpm: int | None = None
    model_rpm: int | None = None
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None

    @property
    def label(self) -> str:
        return f"{self.provider_key}/{self.model_name}"


@dataclass(frozen=True)
class ResolvedNode:
    node_key: str
    enabled: bool
    output: str
    max_attempts: int
    max_tool_steps: int | None
    timeout_s: int
    chain: list[ResolvedModel] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "ResolvedNode":
        return cls(**{**data, "chain": [ResolvedModel(**m) for m in data["chain"]]})


class RegistrySnapshot:
    """The resolved registry as a lesson stores it (JSON), and the gateway reads it back."""

    VERSION = 1

    def __init__(self, nodes: Mapping[str, dict]):
        self._nodes = dict(nodes)

    @classmethod
    def from_json(cls, data: "Mapping | RegistrySnapshot") -> "RegistrySnapshot":
        return data if isinstance(data, RegistrySnapshot) else cls(data["nodes"])

    def to_json(self) -> dict:
        return {"version": self.VERSION, "nodes": self._nodes}

    def node(self, node_key: str) -> ResolvedNode:
        try:
            return ResolvedNode.from_dict(self._nodes[node_key])
        except KeyError:
            raise KeyError(f"Node {node_key!r} is not in the registry snapshot") from None

    def node_keys(self) -> list[str]:
        return list(self._nodes)


class RegistryResolver:
    """Flattens the registry rows into ResolvedNodes (cache-aside: built once, cleared on every registry save)."""

    CACHE_KEY = "llm_registry:resolved"

    def __init__(
        self, *, cache=None, profiles: ProviderProfiles = PROVIDER_PROFILES, specs: NodeSpecCatalog = NODE_SPECS
    ):
        self._cache = cache if cache is not None else default_cache
        self._profiles, self._specs = profiles, specs

    def resolve(self) -> dict[str, ResolvedNode]:
        return {key: ResolvedNode.from_dict(value) for key, value in self._resolved_dicts().items()}

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(self._resolved_dicts())

    def invalidate(self) -> None:
        self._cache.delete(self.CACHE_KEY)

    def _resolved_dicts(self) -> dict[str, dict]:
        data = self._cache.get(self.CACHE_KEY)
        if data is None:
            data = self._build()
            self._cache.set(self.CACHE_KEY, data, timeout=None)
        return data

    def _build(self) -> dict[str, dict]:
        from .models import NodeConfig  # avoid import cycles at app load

        resolved = {}
        nodes = NodeConfig.objects.prefetch_related("bindings__model__provider").filter(node_key__in=self._specs)
        for node in nodes:
            chain = []
            for binding in sorted(node.bindings.all(), key=lambda b: b.priority):
                if not (binding.is_enabled and binding.model.is_enabled and binding.model.provider.is_enabled):
                    continue
                if issues := binding.problems():
                    logger.warning("llm_registry: skipping %s: %s", binding, "; ".join(issues))
                    continue
                chain.append(self._resolve_binding(node, binding))
            resolved[node.node_key] = asdict(
                ResolvedNode(
                    node_key=node.node_key,
                    enabled=node.is_enabled,
                    output=node.spec.output.value,
                    max_attempts=node.max_attempts,
                    max_tool_steps=node.max_tool_steps,
                    timeout_s=node.timeout_s,
                    chain=chain,
                )
            )
        return resolved

    def _resolve_binding(self, node, binding) -> ResolvedModel:
        model, provider = binding.model, binding.model.provider
        params = {**model.default_params, **node.params_override, **binding.params_override}
        effort = binding.reasoning_effort or node.reasoning_effort or node.spec.default_reasoning
        if not model.supports_reasoning:
            effort = Effort.NONE
        params, reasoning = self._profiles.for_kind(provider.kind).apply_reasoning(
            model.reasoning_control, effort, params, disables_sampling=model.reasoning_disables_sampling
        )
        return ResolvedModel(
            provider_key=provider.key,
            provider_kind=provider.kind,
            model_name=model.name,
            params=params,
            reasoning=reasoning,
            reasoning_effort=str(effort),
            structured_output_method=model.structured_output_method,
            api_key_env=provider.api_key_env,
            base_url=provider.base_url,
            max_retries=binding.max_retries,
            provider_rpm=provider.rpm_limit,
            model_rpm=model.rpm_limit,
            input_cost_per_mtok=_float(model.input_cost_per_mtok),
            output_cost_per_mtok=_float(model.output_cost_per_mtok),
        )


def _float(value) -> float | None:
    return float(value) if value is not None else None

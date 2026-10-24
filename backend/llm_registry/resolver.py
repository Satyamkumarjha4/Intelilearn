"""Flatten the registry into plain, serialisable objects the gateway can use.

Precedence (lowest → highest):
    params:    LLMModel.default_params < NodeConfig.params_override < NodeModelBinding.params_override
    reasoning: NodeSpec.default_reasoning < NodeConfig.reasoning_effort < NodeModelBinding.reasoning_effort

The result is cached; any registry save clears the cache (see signals.py). Lessons store a snapshot of it
(`registry_snapshot()`) so admin edits never change a run that is already in progress.
"""

import logging
from dataclasses import asdict, dataclass, field

from django.core.cache import cache

from .node_specs import NODE_SPECS, Effort
from .reasoning import apply_reasoning

logger = logging.getLogger(__name__)

CACHE_KEY = "llm_registry:resolved"
SNAPSHOT_VERSION = 1


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


def _resolve_binding(node, binding) -> ResolvedModel:
    model, provider = binding.model, binding.model.provider
    params = {**model.default_params, **node.params_override, **binding.params_override}
    effort = binding.reasoning_effort or node.reasoning_effort or node.spec.default_reasoning
    if not model.supports_reasoning:
        effort = Effort.NONE
    params, reasoning = apply_reasoning(
        provider.kind, model.reasoning_control, effort, params, disables_sampling=model.reasoning_disables_sampling
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
        input_cost_per_mtok=float(model.input_cost_per_mtok) if model.input_cost_per_mtok is not None else None,
        output_cost_per_mtok=float(model.output_cost_per_mtok) if model.output_cost_per_mtok is not None else None,
    )


def _build() -> dict[str, dict]:
    from .models import NodeConfig  # avoid import cycles at app load

    resolved = {}
    nodes = NodeConfig.objects.prefetch_related("bindings__model__provider").filter(node_key__in=NODE_SPECS)
    for node in nodes:
        chain = []
        for binding in sorted(node.bindings.all(), key=lambda b: b.priority):
            if not (binding.is_enabled and binding.model.is_enabled and binding.model.provider.is_enabled):
                continue
            if issues := binding.problems():
                logger.warning("llm_registry: skipping %s: %s", binding, "; ".join(issues))
                continue
            chain.append(_resolve_binding(node, binding))
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


def _resolved_dicts() -> dict[str, dict]:
    data = cache.get(CACHE_KEY)
    if data is None:
        data = _build()
        cache.set(CACHE_KEY, data, timeout=None)
    return data


def resolve_registry() -> dict[str, ResolvedNode]:
    return {key: ResolvedNode.from_dict(value) for key, value in _resolved_dicts().items()}


def registry_snapshot() -> dict:
    """JSON-serialisable copy of the resolved registry, stored on each lesson when it starts."""
    return {"version": SNAPSHOT_VERSION, "nodes": _resolved_dicts()}


def node_from_snapshot(snapshot: dict, node_key: str) -> ResolvedNode:
    try:
        return ResolvedNode.from_dict(snapshot["nodes"][node_key])
    except KeyError:
        raise KeyError(f"Node {node_key!r} is not in the registry snapshot") from None


def invalidate() -> None:
    cache.delete(CACHE_KEY)

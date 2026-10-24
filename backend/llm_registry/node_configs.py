"""Keep one NodeConfig row per NodeSpec: a new spec in code gets its row (with the spec's defaults) on migrate."""

from .models import NodeConfig
from .node_specs import NODE_SPECS, NodeSpecCatalog
from .resolver import RegistryResolver


class NodeConfigSync:
    def __init__(self, specs: NodeSpecCatalog = NODE_SPECS, resolver: RegistryResolver | None = None):
        self._specs = specs
        self._resolver = resolver if resolver is not None else RegistryResolver()

    def ensure(self, using: str = "default") -> int:
        """Create a NodeConfig for every NodeSpec that doesn't have one yet; return how many were created."""
        existing = set(NodeConfig.objects.using(using).values_list("node_key", flat=True))
        missing = [
            NodeConfig(
                node_key=spec.key,
                reasoning_effort=spec.default_reasoning,
                max_attempts=spec.default_max_attempts,
                max_tool_steps=spec.default_max_tool_steps,
            )
            for key, spec in self._specs.items()
            if key not in existing
        ]
        NodeConfig.objects.using(using).bulk_create(missing)
        if missing:
            self._resolver.invalidate()
        return len(missing)

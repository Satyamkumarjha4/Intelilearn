"""Routing from the console: which models serve each step, in what order, and the profiles that set it all at once.

A step's routing is its settings plus an ordered chain of models. `NodeRoutingValidator` says what is wrong with a
proposed routing (the same checks the Django admin makes, plus the provider's key being set), `NodeRoutingWriter`
replaces a step's routing atomically, `NodeRoutingPresenter` shows one, and `ProfilePreview` shows what loading a seed
profile would do to every step without saving any of it. A save is checked as a whole *before* anything is written.
"""

from dataclasses import dataclass, field
from itertools import chain

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from console.audit import AuditTrail
from llm_registry.models import LLMModel, NodeConfig, NodeModelBinding
from llm_registry.node_specs import NODE_SPECS
from llm_registry.resolver import RegistryResolver
from llm_registry.seed import SEED_PROFILES


@dataclass(frozen=True)
class ProposedBinding:
    """One model in a chain. `model` is None for one that is not in the registry (`label` says which)."""

    model: LLMModel | None
    label: str
    max_retries: int = 2
    enabled: bool = True
    params: dict = field(default_factory=dict)
    reasoning_effort: str = ""


@dataclass(frozen=True)
class ProposedNode:
    """A step's routing as it is, or as it would be."""

    enabled: bool
    reasoning_effort: str
    max_attempts: int
    max_tool_steps: int | None
    timeout_s: int
    params_override: dict
    bindings: tuple[ProposedBinding, ...]

    @classmethod
    def of(cls, node: NodeConfig) -> "ProposedNode":
        """The routing the database has (the node's bindings should be prefetched with their models and providers)."""
        bindings = sorted(node.bindings.all(), key=lambda binding: binding.priority)
        return cls(
            enabled=node.is_enabled,
            reasoning_effort=node.reasoning_effort,
            max_attempts=node.max_attempts,
            max_tool_steps=node.max_tool_steps,
            timeout_s=node.timeout_s,
            params_override=node.params_override,
            bindings=tuple(
                ProposedBinding(
                    model=b.model,
                    label=str(b.model),
                    max_retries=b.max_retries,
                    enabled=b.is_enabled,
                    params=b.params_override,
                    reasoning_effort=b.reasoning_effort,
                )
                for b in bindings
            ),
        )


class NodeRoutingReader:
    def nodes(self) -> list[NodeConfig]:
        """Every step's config, in the order of the specs (the order of a lesson), in four queries."""
        rows = {n.node_key: n for n in NodeConfig.objects.prefetch_related("bindings__model__provider")}
        return [rows[key] for key in NODE_SPECS if key in rows]

    def get(self, key: str) -> NodeConfig | None:
        return NodeConfig.objects.prefetch_related("bindings__model__provider").filter(node_key=key).first()


class NodeRoutingValidator:
    """What is wrong with a proposed routing, by field. Empty means it can be saved."""

    def binding_problems(self, node: NodeConfig, proposed: ProposedNode, binding: ProposedBinding) -> list[str]:
        model = binding.model
        if model is None:
            return [f"{binding.label} is not in your registry. Add it under Models first."]
        problems = []
        if binding.enabled:
            if not (model.is_enabled and model.provider.is_enabled):
                problems.append(f"{binding.label} is switched off. Switch it on, or take it out of the chain.")
            if not model.provider.has_api_key:
                problems.append(
                    f"{model.provider.key} has no API key: set {model.provider.api_key_env} on the server first."
                )
        # What the admin checks for a binding: the capabilities and sizes the step needs, and the parameters merged
        # from the model, the step and the binding. A throwaway row carries the proposed values to the model's
        # own check.
        trial_node = NodeConfig(node_key=node.node_key, params_override=proposed.params_override)
        trial = NodeModelBinding(
            node=trial_node, model=model, params_override=binding.params, reasoning_effort=binding.reasoning_effort
        )
        return problems + trial.problems()

    def problems(self, node: NodeConfig, proposed: ProposedNode) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        try:  # the step's own rules: required steps stay on, tool steps need a step limit and only they do
            NodeConfig(
                node_key=node.node_key,
                is_enabled=proposed.enabled,
                max_tool_steps=proposed.max_tool_steps,
                params_override=proposed.params_override,
            ).clean()
        except DjangoValidationError as exc:
            found.update(
                {("enabled" if f == "is_enabled" else f): messages for f, messages in exc.message_dict.items()}
            )

        messages = self._chain_problems(node, proposed)
        if proposed.enabled and not any(b.enabled for b in proposed.bindings):
            messages.append("Add at least one model that is switched on, or switch the step off.")
        if messages:
            found["bindings"] = messages
        return found

    def _chain_problems(self, node: NodeConfig, proposed: ProposedNode) -> list[str]:
        messages, seen = [], set()
        for position, binding in enumerate(proposed.bindings, start=1):
            who = f"Model {position} ({binding.label})"
            parked = not binding.enabled and binding.model is not None  # switched off in the chain: it is not used
            if not parked:
                messages += [f"{who}: {problem}" for problem in self.binding_problems(node, proposed, binding)]
            if binding.model is not None:
                if binding.model.pk in seen:
                    messages.append(f"{who} is in the chain more than once.")
                seen.add(binding.model.pk)
        return messages


class NodeRoutingPresenter:
    """A step's routing as the API shows it, and the part of it the audit trail keeps."""

    def __init__(self, validator: NodeRoutingValidator | None = None):
        self._validator = validator or NodeRoutingValidator()

    def present(self, node: NodeConfig, proposed: ProposedNode | None = None) -> dict:
        proposed = proposed or ProposedNode.of(node)
        spec = NODE_SPECS[node.node_key]
        return {
            "key": node.node_key,
            "phase": spec.stage.value,
            "description": spec.description,
            "optional": spec.optional,
            "output": spec.output.value,
            "requires": sorted(c.value for c in spec.requires),
            "min_output_tokens": spec.min_output_tokens,
            "min_context": spec.min_context,
            **self._settings(proposed),
            "bindings": [
                {**self._binding(b), "problems": self._validator.binding_problems(node, proposed, b)}
                for b in proposed.bindings
            ],
        }

    def snapshot(self, node: NodeConfig) -> dict:
        """What an audit entry keeps of a step: its settings and its chain (not the derived problems)."""
        proposed = ProposedNode.of(node)
        return {**self._settings(proposed), "bindings": [self._binding(b) for b in proposed.bindings]}

    @staticmethod
    def _settings(proposed: ProposedNode) -> dict:
        return {
            "enabled": proposed.enabled,
            "reasoning_effort": proposed.reasoning_effort,
            "max_attempts": proposed.max_attempts,
            "max_tool_steps": proposed.max_tool_steps,
            "timeout_s": proposed.timeout_s,
            "params_override": proposed.params_override,
        }

    @staticmethod
    def _binding(binding: ProposedBinding) -> dict:
        return {
            "model": binding.model.pk if binding.model else None,
            "model_label": binding.label,
            "enabled": binding.enabled,
            "max_retries": binding.max_retries,
            "overrides": {"params": binding.params, "reasoning_effort": binding.reasoning_effort},
        }


class NodeRoutingWriter:
    def __init__(self, trail: AuditTrail, presenter: NodeRoutingPresenter | None = None):
        self._trail = trail
        self._presenter = presenter or NodeRoutingPresenter()

    def replace(self, node: NodeConfig, proposed: ProposedNode) -> NodeConfig:
        """Make `proposed` the step's routing: its settings and its whole chain, with priorities in the order given,
        and the audit entry, all in one transaction (a failure anywhere leaves the old routing as it was)."""
        before = self._presenter.snapshot(node)
        with transaction.atomic():
            node.is_enabled = proposed.enabled
            node.reasoning_effort = proposed.reasoning_effort
            node.max_attempts = proposed.max_attempts
            node.max_tool_steps = proposed.max_tool_steps
            node.timeout_s = proposed.timeout_s
            node.params_override = proposed.params_override
            node.save()
            node.bindings.all().delete()
            for priority, binding in enumerate(proposed.bindings):
                NodeModelBinding.objects.create(  # one by one: saving each one clears the resolver's cache
                    node=node,
                    model=binding.model,
                    priority=priority,
                    max_retries=binding.max_retries,
                    is_enabled=binding.enabled,
                    params_override=binding.params,
                    reasoning_effort=binding.reasoning_effort,
                )
            after = self._presenter.snapshot(NodeRoutingReader().get(node.node_key))
            self._trail.record("node.update", "node", node.node_key, before=before, after=after)
            # The signals cleared the cache while this was still uncommitted; clear it again once others can see it.
            transaction.on_commit(RegistryResolver().invalidate)
        return NodeRoutingReader().get(node.node_key)


class ProfilePreview:
    """What loading a seed profile (`llm_registry/seed.py`) would do to each step, as `seed_registry` would do it: the
    profile's values replace the step's, and what it does not mention stays. Models are found in the registry by
    provider and name; one that is not there is reported, not created."""

    def __init__(
        self,
        profiles=SEED_PROFILES,
        reader: NodeRoutingReader | None = None,
        validator: NodeRoutingValidator | None = None,
    ):
        self._profiles = profiles
        self._reader = reader or NodeRoutingReader()
        self._validator = validator or NodeRoutingValidator()
        self._presenter = NodeRoutingPresenter(self._validator)

    def listing(self) -> list[dict]:
        return [
            {"name": name, "label": profile.label, "description": profile.description, "nodes": len(profile.nodes)}
            for name, profile in self._profiles.items()
        ]

    def preview(self, name: str) -> dict | None:
        """The preview of profile `name`, or None if there is no such profile."""
        profile = self._profiles.get(name)
        if profile is None:
            return None
        items = {item["node_key"]: item for item in profile().build()["nodes"]}
        models = {(m.provider.key, m.name): m for m in LLMModel.objects.select_related("provider")}
        steps = []
        for node in self._reader.nodes():
            current = ProposedNode.of(node)
            proposed = self._proposed(current, items.get(node.node_key), models)
            problems = list(chain.from_iterable(self._validator.problems(node, proposed).values()))
            steps.append(
                {
                    "key": node.node_key,
                    "changed": proposed != current,
                    "current": self._presenter.present(node, current),
                    "proposed": self._presenter.present(node, proposed),
                    "problems": problems,
                }
            )
        return {
            "profile": name,
            "label": profile.label,
            "nodes": steps,
            "summary": {
                "total": len(steps),
                "changed": sum(step["changed"] for step in steps),
                "blocked": sum(bool(step["problems"]) for step in steps),
            },
        }

    @staticmethod
    def _proposed(current: ProposedNode, item: dict | None, models: dict) -> ProposedNode:
        if item is None:
            return current
        bindings = []
        for entry in sorted(item.get("bindings", []), key=lambda b: b["priority"]):
            model = models.get((entry["provider"], entry["model"]))
            bindings.append(
                ProposedBinding(
                    model=model,
                    label=str(model) if model else f"{entry['provider']}/{entry['model']}",
                    max_retries=entry.get("max_retries", 2),
                    enabled=entry.get("is_enabled", True),
                    params=entry.get("params_override", {}),
                    reasoning_effort=entry.get("reasoning_effort", ""),
                )
            )
        return ProposedNode(
            enabled=item.get("is_enabled", current.enabled),
            reasoning_effort=item.get("reasoning_effort", current.reasoning_effort),
            max_attempts=item.get("max_attempts", current.max_attempts),
            max_tool_steps=item.get("max_tool_steps", current.max_tool_steps),
            timeout_s=item.get("timeout_s", current.timeout_s),
            params_override=item.get("params_override", current.params_override),
            bindings=tuple(bindings) if "bindings" in item else current.bindings,
        )

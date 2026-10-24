"""`manage.py check` warnings for registry problems that would only surface mid-lesson otherwise.
Grouped into one warning per kind of problem, since they usually share a cause (e.g. one missing key)."""

from django.core.checks import Tags, Warning, register
from django.db import DatabaseError


class RegistryHealth:
    def warnings(self) -> list[Warning]:
        from .models import NodeConfig  # checks are registered before the app registry is ready
        from .node_specs import NODE_SPECS

        try:
            nodes = {n.node_key: n for n in NodeConfig.objects.prefetch_related("bindings__model__provider")}
        except DatabaseError:
            return []  # not migrated yet

        missing_config, no_model, no_key, env_names = [], [], [], set()
        for key, spec in NODE_SPECS.items():
            node = nodes.get(key)
            if node is None or not node.is_enabled:
                if not spec.optional:
                    missing_config.append(key)
                continue
            usable = self._usable_bindings(node)
            if not usable:
                no_model.append(key)
            elif not any(b.model.provider.has_api_key for b in usable):
                no_key.append(key)
                env_names |= {b.model.provider.api_key_env for b in usable}

        warnings = []
        if missing_config:
            warnings.append(
                Warning(
                    f"Required nodes without an enabled config: {', '.join(missing_config)}.", id="llm_registry.W001"
                )
            )
        if no_model:
            warnings.append(
                Warning(
                    f"{len(no_model)} node(s) have no usable model: {', '.join(no_model)}.",
                    hint="Bind capable models in the admin, or run `manage.py seed_registry`.",
                    id="llm_registry.W002",
                )
            )
        if no_key:
            warnings.append(
                Warning(
                    f"{len(no_key)} node(s) can't call any model because API keys are missing: {', '.join(no_key)}.",
                    hint=f"Set {' or '.join(sorted(env_names))} in .env.",
                    id="llm_registry.W003",
                )
            )
        return warnings

    @staticmethod
    def _usable_bindings(node) -> list:
        return [
            b
            for b in node.bindings.all()
            if b.is_enabled and b.model.is_enabled and b.model.provider.is_enabled and not b.problems()
        ]


@register(Tags.database)
def registry_check(app_configs=None, **kwargs):
    return RegistryHealth().warnings()


class TracingHealth:
    """Tracing that is switched on but cannot work. Only names of settings are reported, never their values."""

    REQUIRED_ENV = {
        "langsmith": ("LANGSMITH_API_KEY",),
        "langfuse": ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"),
    }

    def warnings(self) -> list[Warning]:
        import os

        from django.conf import settings

        from .tracing import TracingNotAvailable, TracingProviders

        name = (getattr(settings, "LLM_TRACING", "none") or "none").strip().lower()
        try:
            provider = TracingProviders.for_name(name)
        except TracingNotAvailable as exc:
            return [Warning(str(exc), hint="Tracing is off until it is fixed.", id="llm_registry.W010")]
        if name == "none":
            return []
        missing = [var for var in self.REQUIRED_ENV.get(name, ()) if not os.environ.get(var)]
        if missing:
            return [
                Warning(
                    f"LLM_TRACING={name} but {', '.join(missing)} is not set.",
                    hint="Set it in .env, or set LLM_TRACING=none.",
                    id="llm_registry.W011",
                )
            ]
        if name == "langfuse":
            try:
                provider.handler()
            except TracingNotAvailable as exc:
                return [Warning(str(exc), id="llm_registry.W012")]
        return []


@register(Tags.compatibility)
def tracing_check(app_configs=None, **kwargs):
    return TracingHealth().warnings()

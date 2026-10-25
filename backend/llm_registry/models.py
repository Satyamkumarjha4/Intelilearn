import os

from django.core.exceptions import ValidationError
from django.db import models

from .node_specs import NODE_SPECS, Capability, Effort, OutputMode
from .profiles import PROVIDER_PROFILES, ProviderKind, ReasoningControl

EFFORT_CHOICES = [(e.value, e.value.capitalize()) for e in Effort]


class Provider(models.Model):
    """An LLM API vendor and how to reach it. Keys stay in the environment; only the variable name is stored."""

    key = models.SlugField(unique=True, help_text="Short id, e.g. gemini, groq, openai.")
    kind = models.CharField(max_length=30, choices=ProviderKind.CHOICES)
    api_key_env = models.CharField(
        max_length=100,
        blank=True,
        help_text="Name of the environment variable holding the API key, e.g. GEMINI_API_KEY.",
    )
    base_url = models.URLField(blank=True, help_text="Only for Ollama and OpenAI-compatible providers.")
    rpm_limit = models.PositiveIntegerField(
        null=True, blank=True, help_text="Requests per minute across all this provider's models. Empty = no limit."
    )
    is_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.key

    @property
    def has_api_key(self) -> bool:
        return not self.api_key_env or bool(os.environ.get(self.api_key_env))

    @property
    def profile(self):
        return PROVIDER_PROFILES.for_kind(self.kind)

    def clean(self):
        profile = self.profile
        if profile.needs_base_url and not self.base_url:
            raise ValidationError({"base_url": "Required for this provider kind."})
        if not profile.needs_base_url and self.base_url:
            raise ValidationError({"base_url": "Only Ollama and OpenAI-compatible providers take a base URL."})
        if profile.needs_api_key and not self.api_key_env:
            raise ValidationError({"api_key_env": "Name the environment variable that holds this provider's API key."})


class LLMModel(models.Model):
    """One model offered by a provider: defaults, capabilities and limits."""

    class StructuredMethod(models.TextChoices):
        JSON_SCHEMA = "json_schema", "JSON schema"
        FUNCTION_CALLING = "function_calling", "Function calling"
        JSON_MODE = "json_mode", "JSON mode"

    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="models")
    name = models.CharField(max_length=150, help_text="Model id sent to the API, e.g. gemini-2.5-flash.")
    label = models.CharField(max_length=150, blank=True)
    default_params = models.JSONField(default=dict, blank=True, help_text='e.g. {"temperature": 0.4}')

    supports_structured_output = models.BooleanField(default=False)
    structured_output_method = models.CharField(
        max_length=20, choices=StructuredMethod.choices, default=StructuredMethod.JSON_SCHEMA
    )
    supports_tool_calling = models.BooleanField(default=False)
    supports_parallel_tool_calls = models.BooleanField(default=False)
    supports_vision = models.BooleanField(default=False)
    supports_reasoning = models.BooleanField(default=False)
    reasoning_control = models.CharField(max_length=20, choices=ReasoningControl.CHOICES, default=ReasoningControl.NONE)
    reasoning_disables_sampling = models.BooleanField(
        default=False, help_text="Drop temperature/top_p/top_k when reasoning is on (some APIs reject both)."
    )

    context_window = models.PositiveIntegerField(default=128_000)
    max_output_tokens = models.PositiveIntegerField(default=8192)
    rpm_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Requests per minute for this model.")
    input_cost_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    output_cost_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    is_enabled = models.BooleanField(default=True)

    # The latest connectivity test (the console's "Test" button): when, whether it worked, how long the plain text round
    # trip took and, if it did not work, why (already redacted by the prober). Never an input to routing.
    last_probe_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_probe_ok = models.BooleanField(null=True, blank=True, editable=False)
    last_probe_latency_s = models.FloatField(null=True, blank=True, editable=False)
    last_probe_error = models.TextField(blank=True, editable=False)

    class Meta:
        ordering = ["provider__key", "name"]
        constraints = [models.UniqueConstraint(fields=["provider", "name"], name="unique_model_per_provider")]
        verbose_name = "LLM model"

    def __str__(self):
        return f"{self.provider_id and self.provider.key}/{self.name}"

    @property
    def capabilities(self) -> set[Capability]:
        flags = {
            Capability.STRUCTURED_OUTPUT: self.supports_structured_output,
            Capability.TOOL_CALLING: self.supports_tool_calling,
            Capability.VISION: self.supports_vision,
            Capability.REASONING: self.supports_reasoning,
        }
        return {cap for cap, on in flags.items() if on}

    def clean(self):
        errors = {}
        if self.provider_id and (problems := self.provider.profile.validate_params(self.default_params)):
            errors["default_params"] = problems
        if self.supports_reasoning and self.reasoning_control == ReasoningControl.NONE:
            errors["reasoning_control"] = "Choose how reasoning is controlled for a reasoning model."
        if errors:
            raise ValidationError(errors)


class NodeConfig(models.Model):
    """How one graph node runs. One row per NodeSpec, created automatically after migrate."""

    node_key = models.CharField(max_length=60, unique=True, choices=[(k, k) for k in NODE_SPECS])
    is_enabled = models.BooleanField(default=True, help_text="Only optional nodes can be switched off.")
    reasoning_effort = models.CharField(max_length=10, choices=EFFORT_CHOICES, default=Effort.MEDIUM)
    params_override = models.JSONField(default=dict, blank=True)
    max_attempts = models.PositiveSmallIntegerField(default=2, help_text="Generate → validate rounds in the graph.")
    max_tool_steps = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Tool-calling nodes only.")
    timeout_s = models.PositiveIntegerField(default=60, help_text="Per LLM call.")

    class Meta:
        ordering = ["node_key"]
        verbose_name = "node config"

    def __str__(self):
        return self.node_key

    @property
    def spec(self):
        return NODE_SPECS[self.node_key]

    def clean(self):
        spec = self.spec
        errors = {}
        if not self.is_enabled and not spec.optional:
            errors["is_enabled"] = "This node is required by the lesson graph and can't be disabled."
        if self.max_tool_steps is not None and spec.output != OutputMode.TOOLS:
            errors["max_tool_steps"] = "Only tool-calling nodes use a tool-step limit."
        if spec.output == OutputMode.TOOLS and not self.max_tool_steps:
            errors["max_tool_steps"] = "Tool-calling nodes need a tool-step limit."
        if not isinstance(self.params_override, dict):
            errors["params_override"] = "Must be a JSON object."
        if errors:
            raise ValidationError(errors)


class NodeModelBinding(models.Model):
    """Attaches a model to a node. Priority 0 is the primary; higher numbers are fallbacks, tried in order."""

    node = models.ForeignKey(NodeConfig, on_delete=models.CASCADE, related_name="bindings")
    model = models.ForeignKey(LLMModel, on_delete=models.PROTECT, related_name="bindings")
    priority = models.PositiveSmallIntegerField(default=0)
    params_override = models.JSONField(default=dict, blank=True)
    reasoning_effort = models.CharField(
        max_length=10, choices=EFFORT_CHOICES, blank=True, help_text="Blank = use the node's setting."
    )
    max_retries = models.PositiveSmallIntegerField(default=2, help_text="Retries on this model before falling back.")
    is_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["node__node_key", "priority"]
        constraints = [models.UniqueConstraint(fields=["node", "priority"], name="unique_priority_per_node")]

    def __str__(self):
        return f"{self.node_id and self.node.node_key} #{self.priority}: {self.model_id and self.model}"

    def problems(self) -> list[str]:
        """Why this model can't serve this node (empty when it can)."""
        spec, model = self.node.spec, self.model
        issues = []
        missing = spec.requires - model.capabilities
        if missing:
            issues.append(f"{model} lacks {', '.join(sorted(missing))}, which {spec.key} requires.")
        if model.max_output_tokens < spec.min_output_tokens:
            issues.append(
                f"{model} outputs at most {model.max_output_tokens} tokens; {spec.key} needs {spec.min_output_tokens}."
            )
        if model.context_window < spec.min_context:
            issues.append(f"{model} has a {model.context_window}-token context; {spec.key} needs {spec.min_context}.")
        merged = {**model.default_params, **self.node.params_override, **self.params_override}
        issues += model.provider.profile.validate_params(merged)
        return issues

    def clean(self):
        if self.node_id and self.model_id and (issues := self.problems()):
            raise ValidationError(issues)


class ModelCall(models.Model):
    """One call made by the gateway. Read-only log for spotting failing models and fallbacks."""

    class Status(models.TextChoices):
        OK = "ok", "OK"
        RETRYABLE_ERROR = "retryable_error", "Retryable error"
        FATAL_ERROR = "fatal_error", "Fatal error"
        INVALID_OUTPUT = "invalid_output", "Invalid output"

    # Plain UUIDs rather than foreign keys, so the registry doesn't depend on the lessons app.
    lesson_id = models.UUIDField(null=True, blank=True, db_index=True)
    run_id = models.UUIDField(null=True, blank=True, db_index=True)
    node_key = models.CharField(max_length=60, db_index=True)
    provider_key = models.CharField(max_length=50)
    model_name = models.CharField(max_length=150)
    attempt = models.PositiveSmallIntegerField()
    fallback_index = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices)
    error = models.TextField(blank=True)
    latency_ms = models.PositiveIntegerField()  # includes any wait for a rate-limit window
    rate_limit_wait_ms = models.PositiveIntegerField(
        default=0, help_text="Part of the latency spent waiting for a window."
    )
    input_tokens = models.PositiveIntegerField(null=True)
    output_tokens = models.PositiveIntegerField(null=True)
    reasoning_tokens = models.PositiveIntegerField(null=True)
    tool_calls = models.PositiveSmallIntegerField(default=0)
    cost = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        # The console's usage page filters by one model or one node over a time range; created_at is indexed on its own.
        indexes = [
            models.Index(fields=["model_name", "created_at"], name="modelcall_model_created_idx"),
            models.Index(fields=["node_key", "created_at"], name="modelcall_node_created_idx"),
        ]

    def __str__(self):
        return f"{self.node_key} → {self.provider_key}/{self.model_name} ({self.status})"

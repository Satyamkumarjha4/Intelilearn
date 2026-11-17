import os
from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from .node_specs import NODE_SPECS, Capability, Effort, OutputMode
from .profiles import PROVIDER_PROFILES, ProviderKind, ReasoningControl, ReasoningOff

NOT_NEGATIVE = MinValueValidator(0)


def price_field(**kwargs) -> models.DecimalField:
    """US dollars per million tokens, never below zero."""
    return models.DecimalField(max_digits=10, decimal_places=4, validators=[NOT_NEGATIVE], **kwargs)


EFFORT_CHOICES = [(e.value, e.value.capitalize()) for e in Effort]


class Tier(models.TextChoices):
    T0 = "T0", "T0 tiny"
    T1 = "T1", "T1 cheap"
    T2 = "T2", "T2 mid"
    T3 = "T3", "T3 strong"
    T4 = "T4", "T4 premium"


class ModelStatus(models.TextChoices):
    STABLE = "stable", "Stable"
    PREVIEW = "preview", "Preview"
    DEPRECATED = "deprecated", "Deprecated"


class StructuredMode(models.TextChoices):
    STRICT = "strict", "Strict (constrained decoding)"
    BEST_EFFORT = "best_effort", "Best effort"
    OFF = "off", "Off (plain JSON mode)"


class FallThrough(models.TextChoices):
    """The events after which the next layer of a chain is tried."""

    QUOTA = "quota", "A spent quota"
    RATE_LIMIT = "rate_limit", "A per-minute limit"
    SERVER_ERROR = "server_error", "A server error or timeout"
    BAD_REQUEST = "bad_request", "A request the model refuses"
    INVALID_OUTPUT = "invalid_output", "A reply that does not match the schema"
    VALIDATION = "validation", "A reply the lesson's checks reject"


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
    max_request_tokens = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="The most one request may use (its prompt plus the reply it may write). Set it when a provider's "
        "per-minute token limit is small: a binding that could exceed it is skipped. Empty = no limit.",
    )
    # Legacy: a price typed on the model itself. `ModelPrice` rows (a price per window of dates, with its source) win;
    # these two are used only for a model that has none.
    input_cost_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    output_cost_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    is_enabled = models.BooleanField(default=True)

    # What the model is (docs/to_be_developed/model-strategy.md): its tier, whether it is on its way out and when, and
    # what the provider accepts for reasoning and structured output.
    tier = models.CharField(max_length=2, choices=Tier.choices, blank=True)
    status = models.CharField(max_length=12, choices=ModelStatus.choices, default=ModelStatus.STABLE)
    shutdown_on = models.DateField(
        null=True, blank=True, help_text="The day the provider stops serving it (or reroutes it), when it says so."
    )
    reasoning_levels = models.JSONField(
        default=list,
        blank=True,
        help_text='The reasoning levels the model accepts, lowest first, e.g. ["minimal", "low", "medium", "high"]. '
        "Empty = low, medium and high.",
    )
    reasoning_off = models.CharField(
        max_length=12,
        choices=ReasoningOff.CHOICES,
        blank=True,
        help_text="How 'no reasoning' is asked for: the model's lowest level, a disabled switch, effort none, or "
        "(blank) nothing is sent and the provider's own default applies.",
    )
    strict_structured = models.BooleanField(
        default=False, help_text="The provider can guarantee the reply matches the schema (constrained decoding)."
    )
    min_cache_tokens = models.PositiveIntegerField(
        null=True, blank=True, help_text="The shortest prompt the provider will cache. Empty = unknown."
    )

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
        profile = self.provider_id and self.provider.profile
        if profile and (problem := profile.rejects_reasoning_control(self.name, self.reasoning_control)):
            errors["reasoning_control"] = problem
        if not isinstance(self.reasoning_levels, list) or not all(isinstance(v, str) for v in self.reasoning_levels):
            errors["reasoning_levels"] = 'Must be a list of level names, e.g. ["low", "medium", "high"].'
        if errors:
            raise ValidationError(errors)


class ModelPriceQuerySet(models.QuerySet):
    def in_effect(self, provider_key: str, model_name: str, day: date) -> "ModelPrice | None":
        """The row whose window holds `day` (both ends inclusive), or None."""
        return (
            self.filter(model__provider__key=provider_key, model__name=model_name)
            .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=day))
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=day))
            .order_by("-valid_from")
            .first()
        )

    def next_after(self, provider_key: str, model_name: str, day: date) -> "ModelPrice | None":
        """The first row that starts after `day`: what the price becomes, and when."""
        return (
            self.filter(model__provider__key=provider_key, model__name=model_name, valid_from__gt=day)
            .order_by("valid_from")
            .first()
        )


class ModelPrice(models.Model):
    """A model's price in US dollars per million tokens for a window of dates, with the page it was read from and the
    day it was read. A change of price is a new row, so a `ModelCall` keeps the price it was billed at. `output` is
    what thinking tokens are billed at too: every provider bills them as output."""

    model = models.ForeignKey(LLMModel, on_delete=models.CASCADE, related_name="prices")
    input_per_mtok = price_field()
    output_per_mtok = price_field(help_text="Thinking tokens are billed at it.")
    cached_input_per_mtok = price_field(null=True, blank=True)
    cache_write_per_mtok = price_field(null=True, blank=True)
    long_context_threshold = models.PositiveIntegerField(
        null=True, blank=True, help_text="A prompt with more input tokens than this is billed at the long prices."
    )
    long_input_per_mtok = price_field(null=True, blank=True)
    long_output_per_mtok = price_field(null=True, blank=True)
    long_cached_input_per_mtok = price_field(null=True, blank=True)
    batch_discount = models.DecimalField(
        max_digits=4, decimal_places=3, default=0.5, help_text="The share a batch call saves (0.5 = half price)."
    )
    valid_from = models.DateField(null=True, blank=True, help_text="First day it applies. Empty = from the beginning.")
    valid_until = models.DateField(null=True, blank=True, help_text="Last day it applies. Empty = until replaced.")
    source_url = models.URLField(max_length=300, help_text="The provider's own page it was read from.")
    checked_on = models.DateField(help_text="The day that page was read.")
    note = models.TextField(blank=True)

    objects = ModelPriceQuerySet.as_manager()

    class Meta:
        ordering = ["model__provider__key", "model__name", "valid_from"]

    def __str__(self):
        window = f"{self.valid_from or 'start'} to {self.valid_until or 'open'}"
        return f"{self.model_id and self.model} ${self.input_per_mtok} / ${self.output_per_mtok} ({window})"

    def _overlaps(self, other: "ModelPrice") -> bool:
        """Two windows overlap unless one ends before the other starts (an empty end means open)."""

        def ends_before(first_until, second_from) -> bool:
            return first_until is not None and second_from is not None and first_until < second_from

        return not (ends_before(self.valid_until, other.valid_from) or ends_before(other.valid_until, self.valid_from))

    def clean(self):
        errors = {}
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            errors["valid_until"] = "A price cannot end before it starts."
        long = [self.long_context_threshold, self.long_input_per_mtok, self.long_output_per_mtok]
        if any(v is not None for v in long) and any(v is None for v in long):
            errors["long_context_threshold"] = "Give the threshold, the long input price and the long output price."
        if self.model_id and not errors:
            others = ModelPrice.objects.filter(model_id=self.model_id).exclude(pk=self.pk)
            for other in others:
                if self._overlaps(other):
                    errors["valid_from"] = f"These dates overlap another price of this model ({other})."
                    break
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
    max_output_tokens = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="The most this layer may write, thinking included (sent as max_tokens). Empty = the model's own.",
    )
    timeout_s = models.PositiveIntegerField(
        null=True, blank=True, help_text="Per call on this layer. Empty = the node's timeout."
    )
    structured_mode = models.CharField(
        max_length=12,
        choices=StructuredMode.choices,
        blank=True,
        help_text="Blank = strict when the model supports it, otherwise best effort.",
    )
    fall_through_on = models.JSONField(
        default=list,
        blank=True,
        help_text="Events after which the next layer is tried. Empty = every failure (today's behaviour).",
    )

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
        if model.max_request_tokens:
            written = self.max_output_tokens or merged.get("max_tokens") or model.max_output_tokens
            if spec.typical_input_tokens + written > model.max_request_tokens:
                issues.append(
                    f"{model} allows {model.max_request_tokens} tokens in one request; {spec.key} sends about "
                    f"{spec.typical_input_tokens} and may write {written}. Lower max_output_tokens."
                )
        return issues

    def clean(self):
        errors = []
        events = {event.value for event in FallThrough}
        if not isinstance(self.fall_through_on, list) or not set(self.fall_through_on) <= events:
            errors.append(f"fall_through_on must be a list of: {', '.join(sorted(events))}.")
        if self.node_id and self.model_id:
            errors += self.problems()
        if errors:
            raise ValidationError(errors)


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
    quiz_id = models.UUIDField(null=True, blank=True, db_index=True)  # the quick quiz it was for (phase 9.6)
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
    cached_input_tokens = models.PositiveIntegerField(null=True, help_text="Input tokens served from the cache.")
    cache_write_tokens = models.PositiveIntegerField(null=True, help_text="Input tokens written to the cache.")
    tool_calls = models.PositiveSmallIntegerField(default=0)
    # US dollars, priced with the `ModelPrice` row in force on the day of the call (cached input and cache writes at
    # their own prices; thinking is part of the output tokens). `cost` is the same figure, kept for the readers that
    # have not moved to `cost_usd` yet.
    cost = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    # What the model wrote when a validator then refused it, and what the validator said: staff-only evidence of whether
    # the model or the rule was wrong. It can hold what a lesson was about, so it is emptied after
    # `REJECTED_OUTPUT_RETENTION_DAYS` by the daily purge and deleted with the lesson (see `RejectedOutputs`).
    rejected_output = models.TextField(blank=True, default="")
    rejection = models.TextField(blank=True, default="")
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

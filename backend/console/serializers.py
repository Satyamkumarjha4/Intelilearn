"""Shapes of the console API. Services return plain dicts; these say what each looks like (and so what Swagger shows).

Money is a decimal string in US dollars with six places, the precision calls are stored with; times are ISO 8601.
"""

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from console.models import AuditEntry
from console.outcomes import CallOutcomes
from console.periods import Periods
from console.services.registry import ModelService
from console.services.runs import TimelinePhase
from lessons.models import FlowSettings, GraphRun
from llm_registry.models import EFFORT_CHOICES, LLMModel, ModelCall, Provider
from llm_registry.node_specs import Stage

MONEY = {"max_digits": 16, "decimal_places": 6}

# Choice lists that appear in more than one component, named once in SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"].
HEALTH_STATUSES = ["ok", "degraded"]
ROUTING_PHASES = [stage.value for stage in Stage]
TIMELINE_PHASES = [phase.value for phase in TimelinePhase]


class MoneyField(serializers.DecimalField):
    def __init__(self, **kwargs):
        super().__init__(**{**MONEY, **kwargs})


# --- overview ------------------------------------------------------------------------------------------------------


class RangeQuerySerializer(serializers.Serializer):
    range = serializers.ChoiceField(choices=Periods().keys(), default="7d", help_text="today, 7d (default) or 30d.")


class ConsoleHealthComponentSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    latency_ms = serializers.IntegerField()
    detail = serializers.CharField()


class ConsoleHealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=HEALTH_STATUSES)
    database = ConsoleHealthComponentSerializer()
    redis = ConsoleHealthComponentSerializer()
    celery = ConsoleHealthComponentSerializer()
    workers = serializers.IntegerField(help_text="Celery workers that answered a ping.")


class PeriodSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class LessonCountsSerializer(serializers.Serializer):
    started = serializers.IntegerField(help_text="Lessons created in the range.")
    finished = serializers.IntegerField(help_text="Lessons that became ready in the range.")
    failed = serializers.IntegerField(help_text="Lessons that failed in the range.")
    previous_started = serializers.IntegerField(help_text="Lessons created in the equally long range before it.")
    previous_finished = serializers.IntegerField(help_text="Lessons that became ready in that range before it.")


class SpendSerializer(serializers.Serializer):
    range_total = MoneyField()
    per_lesson_avg = MoneyField(help_text="Range total over the lessons that made calls in it.")
    month_to_date = MoneyField()
    monthly_budget = MoneyField(help_text="`CONSOLE_MONTHLY_BUDGET_USD`.")


class CallCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    ok = serializers.IntegerField(help_text="Worked on the first attempt.")
    retried = serializers.IntegerField(help_text="Worked, but on a retry (attempt 2 or later).")
    failed = serializers.IntegerField(help_text="Did not work: any status but ok. ok + retried + failed = total.")
    fallbacks = serializers.IntegerField(help_text="Attempts on a fallback model (fallback_index above 0), any result.")


class DailySpendSerializer(serializers.Serializer):
    date = serializers.DateField()
    by_provider = serializers.DictField(child=MoneyField(), help_text="Provider key → spend that day.")


class DailyActivitySerializer(serializers.Serializer):
    date = serializers.DateField()
    lessons_started = serializers.IntegerField()
    calls_total = serializers.IntegerField()
    calls_worked = serializers.IntegerField(help_text="Calls with status ok, on any attempt.")


class FunnelSerializer(serializers.Serializer):
    started = serializers.IntegerField()
    quick_check_done = serializers.IntegerField()
    built = serializers.IntegerField(help_text="Ready lessons (not study-sheet ones).")
    test_submitted = serializers.IntegerField()
    study_sheets = serializers.IntegerField(help_text="Ready lessons that went to study sheets (mastery).")
    failed_building = serializers.IntegerField()
    waiting = serializers.IntegerField(help_text="Waiting for the learner (a quiz or a sheet choice).")


class SlowestStepSerializer(serializers.Serializer):
    node = serializers.CharField()
    p95_s = serializers.FloatField(help_text="95th percentile call time in seconds, from calls that worked.")


class AttentionSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["lessons_failed", "model_failing", "rate_limit_waits", "provider_key_missing"]
    )
    severity = serializers.ChoiceField(choices=["error", "warning", "info"])
    title = serializers.CharField()
    detail = serializers.CharField()
    link = serializers.CharField(help_text="A console page, as a path.")


class OverviewSerializer(serializers.Serializer):
    range = serializers.ChoiceField(choices=Periods().keys())
    period = PeriodSerializer()
    health = ConsoleHealthSerializer()
    lessons = LessonCountsSerializer()
    spend = SpendSerializer()
    calls = CallCountsSerializer()
    daily_spend = DailySpendSerializer(
        many=True, help_text="14 days for today and 7d, 30 for 30d; empty days included."
    )
    daily_activity = DailyActivitySerializer(many=True, help_text="Lessons started and calls per day, for sparklines.")
    funnel = FunnelSerializer()
    slowest_steps = SlowestStepSerializer(many=True, help_text="The six slowest.")
    attention = AttentionSerializer(many=True, help_text="Most serious first.")


# --- usage ---------------------------------------------------------------------------------------------------------


class UsageQuerySerializer(serializers.Serializer):
    range = serializers.ChoiceField(
        choices=[*Periods().keys(), "custom"],
        default="7d",
        help_text="today, 7d (default), 30d, or custom: whole days from `start` to `end`.",
    )
    start = serializers.DateField(required=False, help_text="First day (YYYY-MM-DD) of a custom range.")
    end = serializers.DateField(required=False, help_text="Last day, included; a custom range is at most a year.")
    provider = serializers.CharField(required=False, allow_blank=True, help_text="Provider key, e.g. gemini.")
    model = serializers.CharField(required=False, allow_blank=True, help_text="Model name as sent to the API.")
    node = serializers.CharField(required=False, allow_blank=True, help_text="Lesson step, e.g. page.generate.")
    outcome = serializers.ChoiceField(
        choices=CallOutcomes.NAMES,
        required=False,
        allow_blank=True,
        help_text=(
            "`ok`: worked first time. `retried`: worked, but on a retry (attempt 2 or later). `failed`: any other "
            "status. A fallback is an attempt on a later model of the step's chain; a retry attempt is attempt > 1."
        ),
    )

    def validate(self, attrs):
        if attrs["range"] != "custom":
            attrs.pop("start", None)  # dates only mean something for a custom range
            attrs.pop("end", None)
            return attrs
        missing = {name: ["Needed for a custom range."] for name in ("start", "end") if name not in attrs}
        if missing:
            raise serializers.ValidationError(missing)
        try:
            Periods().custom(attrs["start"], attrs["end"])
        except ValueError as exc:
            raise serializers.ValidationError({"end": [str(exc)]}) from exc
        return attrs


class UsageKpisSerializer(serializers.Serializer):
    calls = serializers.IntegerField(help_text="Attempts: a retry or a fallback is another call.")
    tokens_in = serializers.IntegerField()
    tokens_out = serializers.IntegerField()
    spend = MoneyField()
    median_latency_s = serializers.FloatField(allow_null=True, help_text="Of the calls that worked; null if none did.")
    p95_latency_s = serializers.FloatField(allow_null=True)


class UsageByModelSerializer(serializers.Serializer):
    model = serializers.CharField()
    provider = serializers.CharField()
    median_s = serializers.FloatField(allow_null=True)
    p95_s = serializers.FloatField(allow_null=True)
    ok = serializers.IntegerField()
    retried = serializers.IntegerField()
    failed = serializers.IntegerField()
    calls = serializers.IntegerField(help_text="ok + retried + failed.")
    spend = MoneyField()


class UsageByNodeSerializer(serializers.Serializer):
    node = serializers.CharField()
    calls = serializers.IntegerField()
    ok_pct = serializers.FloatField(help_text="Share of calls that worked (first time or on a retry), 0 to 100.")
    retries = serializers.IntegerField(help_text="Retry attempts (attempt above 1), whatever came of them.")
    fallbacks = serializers.IntegerField(help_text="Attempts on a fallback model, whatever came of them.")
    tokens_k = serializers.FloatField(help_text="Thousands of tokens, in and out.")
    spend = MoneyField()
    p95_s = serializers.FloatField(allow_null=True)


class UsageSerializer(serializers.Serializer):
    range = serializers.ChoiceField(choices=[*Periods().keys(), "custom"])
    period = PeriodSerializer()
    kpis = UsageKpisSerializer()
    by_model = UsageByModelSerializer(many=True, help_text="Busiest first.")
    by_node = UsageByNodeSerializer(many=True, help_text="Busiest first.")


# --- runs ----------------------------------------------------------------------------------------------------------


class RunQuerySerializer(serializers.Serializer):
    status = serializers.CharField(
        required=False, allow_blank=True, help_text="One run status, or several separated by commas."
    )
    graph = serializers.CharField(
        required=False, allow_blank=True, help_text="One graph, or several separated by commas."
    )
    q = serializers.CharField(
        required=False, allow_blank=True, help_text="Search the lesson topic, learner name or email."
    )

    CHOICES = {"status": GraphRun.Status.values, "graph": GraphRun.Graph.values}

    def _split(self, field: str, value: str) -> list[str]:
        values = [part.strip() for part in value.split(",") if part.strip()]
        unknown = [part for part in values if part not in self.CHOICES[field]]
        if unknown:
            raise serializers.ValidationError(f"Unknown {field}: {', '.join(unknown)}.")
        return values

    def validate_status(self, value):
        return self._split("status", value)

    def validate_graph(self, value):
        return self._split("graph", value)


class RunRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    lesson_id = serializers.UUIDField()
    topic = serializers.CharField(source="lesson.topic")
    learner_name = serializers.CharField(source="lesson.owner.name")
    graph = serializers.ChoiceField(choices=GraphRun.Graph.choices)
    trigger = serializers.ChoiceField(choices=GraphRun.Trigger.choices)
    status = serializers.ChoiceField(choices=GraphRun.Status.choices)
    stage = serializers.CharField(source="lesson.stage", help_text="Where the lesson itself is (a lesson stage).")
    duration_s = serializers.SerializerMethodField(
        help_text="Start to finish; so far for a run in progress; null if it has not started."
    )
    calls = serializers.IntegerField(source="call_count", help_text="Model calls the run made.")
    cost = MoneyField(source="cost_sum")
    created_at = serializers.DateTimeField()

    def get_duration_s(self, run) -> float | None:
        if run.started_at is None:
            return None
        end = run.finished_at or (timezone.now() if run.is_active else None)
        return None if end is None else max(0.0, (end - run.started_at).total_seconds())


class TimelineStepSerializer(serializers.Serializer):
    node = serializers.CharField(help_text="The graph node's name.")
    phase = serializers.ChoiceField(choices=TIMELINE_PHASES)
    start_offset_s = serializers.FloatField(
        allow_null=True, help_text="Seconds after the run started; null if unknown."
    )
    duration_s = serializers.FloatField(
        allow_null=True, help_text="First start to last finish; null if waiting or unknown."
    )
    state = serializers.ChoiceField(choices=["ran", "retried", "failed", "waiting"])


class RunCallSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    node = serializers.CharField()
    provider = serializers.CharField()
    model = serializers.CharField()
    attempt = serializers.IntegerField(help_text="1 for the first try on this model.")
    fallback_index = serializers.IntegerField(help_text="0 for the step's first model, 1 for its second, …")
    status = serializers.ChoiceField(choices=ModelCall.Status.choices)
    outcome = serializers.ChoiceField(choices=CallOutcomes.NAMES)
    latency_s = serializers.FloatField(help_text="Includes any wait for a rate-limit window.")
    tokens_in = serializers.IntegerField(allow_null=True)
    tokens_out = serializers.IntegerField(allow_null=True)
    tool_calls = serializers.IntegerField()
    cost = MoneyField(allow_null=True)
    error = serializers.CharField(help_text="Already stripped of secrets.")


class RunDetailSerializer(RunRowSerializer):
    error = serializers.CharField()
    started_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    timeline = TimelineStepSerializer(many=True)
    model_calls = RunCallSerializer(many=True, source="recent_calls", help_text="The last 20 calls, newest first.")
    can_retry = serializers.BooleanField(help_text="Retry would be accepted.")
    can_cancel = serializers.BooleanField(help_text="The run is queued or running.")


class RunRetriedSerializer(serializers.Serializer):
    run_id = serializers.UUIDField(help_text="The new run.")
    lesson_id = serializers.UUIDField()


class RunCancelledSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=GraphRun.Status.choices)


# --- providers and models ------------------------------------------------------------------------------------------


class RejectUnknownFields:
    """Mixin for input serializers: a field that cannot be set here is an error, not silently ignored (so a client that
    tries to send an API key or move a model to another provider is told no)."""

    def to_internal_value(self, data):
        settable = {field.field_name for field in self._writable_fields}
        refused = {key: ["This cannot be set here."] for key in data if key not in settable}
        if refused:
            raise serializers.ValidationError(refused)
        return super().to_internal_value(data)


class ProviderSerializer(serializers.ModelSerializer):
    api_key_set = serializers.BooleanField(
        source="has_api_key", read_only=True, help_text="Whether that variable is set on the server (never its value)."
    )
    enabled = serializers.BooleanField(source="is_enabled")
    models_count = serializers.IntegerField(read_only=True)
    spend_7d = MoneyField(read_only=True, help_text="Spend of the last 7 days (as the 7d range).")

    class Meta:
        model = Provider
        fields = [
            "key",
            "kind",
            "api_key_env",
            "api_key_set",
            "base_url",
            "rpm_limit",
            "enabled",
            "models_count",
            "spend_7d",
        ]
        read_only_fields = fields


class ProviderUpdateSerializer(RejectUnknownFields, serializers.ModelSerializer):
    enabled = serializers.BooleanField(source="is_enabled", required=False)
    rpm_limit = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    base_url = serializers.URLField(allow_blank=True, required=False)

    class Meta:
        model = Provider
        fields = ["rpm_limit", "base_url", "enabled"]


class LastProbeSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    ok = serializers.BooleanField()
    latency_s = serializers.FloatField(allow_null=True, help_text="Of the plain text call.")
    error = serializers.CharField(allow_blank=True, help_text="Empty when it worked.")


class ModelSerializer(serializers.ModelSerializer):
    provider = serializers.SlugRelatedField(slug_field="key", queryset=Provider.objects.all())
    enabled = serializers.BooleanField(source="is_enabled", required=False)
    api_key_set = serializers.BooleanField(source="provider.has_api_key", read_only=True)
    bound_nodes = serializers.SerializerMethodField(help_text="The steps (node keys) that use the model.")
    last_probe = serializers.SerializerMethodField()

    class Meta:
        model = LLMModel
        fields = [
            "id", "provider", "name", "label", "enabled", "api_key_set", "default_params",
            "supports_structured_output", "structured_output_method", "supports_tool_calling",
            "supports_parallel_tool_calls", "supports_vision", "supports_reasoning", "reasoning_control",
            "reasoning_disables_sampling", "context_window", "max_output_tokens", "rpm_limit",
            "input_cost_per_mtok", "output_cost_per_mtok", "bound_nodes", "last_probe",
        ]  # fmt: skip
        read_only_fields = ["id"]
        validators = []  # the model's own full_clean() checks uniqueness, with the admin's message
        extra_kwargs = {
            "context_window": {"min_value": 1},
            "max_output_tokens": {"min_value": 1},
            "rpm_limit": {"min_value": 1},
            "name": {"max_length": 150},
        }

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_bound_nodes(self, model) -> list[str]:
        return sorted({binding.node.node_key for binding in model.bindings.all()})

    @extend_schema_field(LastProbeSerializer(allow_null=True))
    def get_last_probe(self, model):
        return ModelService.last_probe(model)


class ModelCreateSerializer(RejectUnknownFields, ModelSerializer):
    class Meta(ModelSerializer.Meta):
        read_only_fields = ["id", "bound_nodes", "last_probe", "api_key_set"]


class ModelUpdateSerializer(ModelCreateSerializer):
    """Like creating one, but its provider is fixed (a model is the provider's) and nothing is required."""

    provider = serializers.SlugRelatedField(slug_field="key", read_only=True)


class ProbeCheckSerializer(serializers.Serializer):
    capability = serializers.CharField(help_text="text, structured_output, tool_calling, vision, reasoning or setup.")
    ok = serializers.BooleanField()
    latency_s = serializers.FloatField()
    detail = serializers.CharField(help_text="What happened, already stripped of secrets.")


class ProbeSerializer(serializers.Serializer):
    ok = serializers.BooleanField(help_text="Every check the model's declared capabilities call for passed.")
    latency_s = serializers.FloatField(allow_null=True, help_text="Of the plain text call; null if it never ran.")
    error = serializers.CharField(allow_null=True, help_text="The first failure, as `capability: detail`.")
    checks = ProbeCheckSerializer(many=True)


# --- routing -------------------------------------------------------------------------------------------------------

EFFORTS = [value for value, _ in EFFORT_CHOICES]


class BindingOverridesSerializer(serializers.Serializer):
    params = serializers.DictField(
        default=dict, help_text='Parameters for this model on this step, e.g. {"temperature": 0.2}.'
    )
    reasoning_effort = serializers.ChoiceField(
        choices=EFFORTS, allow_blank=True, default="", help_text="Blank: the step's."
    )


class BindingInputSerializer(serializers.Serializer):
    model = serializers.IntegerField(help_text="A model's id (`GET /models`).")
    enabled = serializers.BooleanField(default=True, help_text="False parks the model in the chain without using it.")
    max_retries = serializers.IntegerField(
        min_value=0, max_value=10, default=2, help_text="Retries on this model before the next."
    )
    overrides = BindingOverridesSerializer(default=dict)


class BindingSerializer(serializers.Serializer):
    model = serializers.IntegerField(
        allow_null=True, help_text="The model's id; null for a model a profile names that is not in the registry."
    )
    model_label = serializers.CharField(help_text="provider/name")
    enabled = serializers.BooleanField()
    max_retries = serializers.IntegerField()
    overrides = BindingOverridesSerializer()
    problems = serializers.ListField(
        child=serializers.CharField(), help_text="Why this model cannot serve this step; empty if it can."
    )


class NodeRoutingInputSerializer(RejectUnknownFields, serializers.Serializer):
    """The whole routing of one step: a save replaces what was there, so every setting is required."""

    enabled = serializers.BooleanField(help_text="Only optional steps can be switched off.")
    reasoning_effort = serializers.ChoiceField(choices=EFFORTS)
    max_attempts = serializers.IntegerField(
        min_value=1, max_value=10, help_text="Generate and check rounds in the graph."
    )
    max_tool_steps = serializers.IntegerField(
        min_value=1, max_value=20, allow_null=True, default=None, help_text="Tool-calling steps only."
    )
    timeout_s = serializers.IntegerField(min_value=1, max_value=600, help_text="Per model call.")
    params_override = serializers.DictField(default=dict)
    bindings = BindingInputSerializer(
        many=True, max_length=10, allow_empty=True, help_text="The chain, first choice first."
    )


class NodeRoutingSerializer(serializers.Serializer):
    key = serializers.CharField()
    phase = serializers.ChoiceField(choices=ROUTING_PHASES)
    description = serializers.CharField()
    optional = serializers.BooleanField(help_text="Optional steps can be switched off; required ones cannot.")
    output = serializers.CharField()
    requires = serializers.ListField(
        child=serializers.CharField(), help_text="Capabilities a model needs for this step."
    )
    min_output_tokens = serializers.IntegerField()
    min_context = serializers.IntegerField()
    enabled = serializers.BooleanField()
    reasoning_effort = serializers.ChoiceField(choices=EFFORTS)
    max_attempts = serializers.IntegerField()
    max_tool_steps = serializers.IntegerField(allow_null=True)
    timeout_s = serializers.IntegerField()
    params_override = serializers.DictField()
    bindings = BindingSerializer(many=True, help_text="In priority order.")


class PhaseRoutingSerializer(serializers.Serializer):
    phase = serializers.ChoiceField(choices=ROUTING_PHASES)
    nodes = NodeRoutingSerializer(many=True)


class RoutingSerializer(serializers.Serializer):
    phases = PhaseRoutingSerializer(many=True, help_text="In the order of a lesson.")


class RoutingProfileSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()
    nodes = serializers.IntegerField(help_text="Steps the profile sets.")


class ProfileStepSerializer(serializers.Serializer):
    key = serializers.CharField()
    changed = serializers.BooleanField()
    current = NodeRoutingSerializer()
    proposed = NodeRoutingSerializer(help_text="Has the shape of a `PUT /nodes/{key}` body, with `model` ids.")
    problems = serializers.ListField(
        child=serializers.CharField(), help_text="Why the proposal cannot be saved as it is."
    )


class ProfilePreviewSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    changed = serializers.IntegerField()
    blocked = serializers.IntegerField(help_text="Steps whose proposal has problems.")


class ProfilePreviewSerializer(serializers.Serializer):
    profile = serializers.CharField()
    label = serializers.CharField()
    nodes = ProfileStepSerializer(many=True)
    summary = ProfilePreviewSummarySerializer()


# --- flow settings -------------------------------------------------------------------------------------------------


class RoutingThresholdsSerializer(serializers.Serializer):
    questions_total = serializers.IntegerField(help_text="Questions in the quick check.")
    foundations_max = serializers.IntegerField(help_text="A score at or below this goes to the foundations first.")
    mastery_min = serializers.IntegerField(help_text="The lowest score that can count as mastery (study sheets).")


class FlowSettingsInputSerializer(RejectUnknownFields, serializers.ModelSerializer):
    """Which fields can be sent, and their types. The admin form's validation runs on top, in the service."""

    class Meta:
        model = FlowSettings
        exclude = ["id"]
        validators = []
        extra_kwargs = {}

    def get_fields(self):
        fields = super().get_fields()
        for field in fields.values():
            field.required = False  # a change is partial, but the same serializer documents the whole shape
        return fields


class FlowSettingsSerializer(serializers.ModelSerializer):
    routing_thresholds = RoutingThresholdsSerializer(read_only=True)

    class Meta:
        model = FlowSettings
        exclude = ["id"]
        read_only_fields = ["id"]


# --- learners ------------------------------------------------------------------------------------------------------


class LearnerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.EmailField()
    education_level = serializers.SerializerMethodField()
    grade_or_year = serializers.SerializerMethodField()
    goal = serializers.SerializerMethodField()
    preferred_language = serializers.SerializerMethodField()
    lessons_count = serializers.IntegerField()
    last_active_at = serializers.DateTimeField(
        source="last_activity", allow_null=True, help_text="The later of their latest lesson activity and last sign-in."
    )
    profile_complete = serializers.SerializerMethodField()
    is_staff = serializers.BooleanField()
    joined_at = serializers.DateTimeField(source="date_joined")

    def _profile(self, member):
        return getattr(member, "profile", None)

    def _field(self, member, name: str, default: str = "") -> str:
        profile = self._profile(member)
        return getattr(profile, name) if profile else default

    def get_education_level(self, member) -> str:
        return self._field(member, "education_level")

    def get_grade_or_year(self, member) -> str:
        return self._field(member, "grade_or_year")

    def get_goal(self, member) -> str:
        return self._field(member, "goal")

    def get_preferred_language(self, member) -> str:
        return self._field(member, "preferred_language", "en")

    def get_profile_complete(self, member) -> bool:
        profile = self._profile(member)
        return bool(profile and profile.is_complete)


class LearnerSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    active_7d = serializers.IntegerField(help_text="Signed in or had lesson activity in the last 7 days.")
    profile_complete = serializers.IntegerField()
    staff = serializers.IntegerField()


class LearnerPageSerializer(serializers.Serializer):
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = LearnerSerializer(many=True)
    summary = LearnerSummarySerializer(help_text="Counts over every learner, whatever the search.")


# --- audit ---------------------------------------------------------------------------------------------------------


class AuditActorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.EmailField()


class AuditEntrySerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField(help_text="Null once the account is deleted; `actor_email` stays.")
    changed_fields = serializers.SerializerMethodField(
        help_text="The top-level fields that differ between `before` and `after`."
    )

    class Meta:
        model = AuditEntry
        fields = ["id", "actor", "actor_email", "action", "target_type", "target_id", "before", "after",
                  "changed_fields", "created_at"]  # fmt: skip
        read_only_fields = fields

    @extend_schema_field(AuditActorSerializer(allow_null=True))
    def get_actor(self, entry):
        actor = entry.actor
        return None if actor is None else {"id": actor.id, "name": actor.name, "email": actor.email}

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_changed_fields(self, entry) -> list[str]:
        before, after = entry.before or {}, entry.after or {}
        if not isinstance(before, dict) or not isinstance(after, dict):
            return []
        return sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))

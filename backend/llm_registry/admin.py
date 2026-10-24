import json

from django import forms
from django.contrib import admin, messages
from django.db import models
from django.http import HttpResponse
from django.utils.html import format_html, format_html_join

from .models import LLMModel, ModelCall, NodeConfig, NodeModelBinding, Provider
from .probes import ModelProber
from .serialization import RegistrySerializer

# JSON fields hold small parameter objects; the default textarea is far too large, especially inline.
COMPACT_JSON = {models.JSONField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 36})}}


def _yes_no(ok: bool, yes="✔", no="✘"):
    return format_html('<span style="color:{}">{}</span>', "#16a34a" if ok else "#dc2626", yes if ok else no)


@admin.action(description="Export the whole registry as JSON")
def export_json(modeladmin, request, queryset):
    response = HttpResponse(json.dumps(RegistrySerializer().export(), indent=2), content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="llm-registry.json"'
    return response


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ["key", "kind", "api_key_env", "key_present", "rpm_limit", "is_enabled"]
    list_filter = ["kind", "is_enabled"]
    actions = [export_json]

    @admin.display(description="Key set?")
    def key_present(self, obj):
        return _yes_no(obj.has_api_key)


@admin.register(LLMModel)
class LLMModelAdmin(admin.ModelAdmin):
    formfield_overrides = COMPACT_JSON
    list_display = ["__str__", "label", "capability_flags", "context_window", "max_output_tokens", "is_enabled"]
    list_filter = ["provider", "is_enabled", "supports_tool_calling", "supports_vision", "supports_reasoning"]
    search_fields = ["name", "label"]
    actions = ["test_model", export_json]
    fieldsets = [
        (None, {"fields": ["provider", "name", "label", "is_enabled", "default_params"]}),
        (
            "Capabilities",
            {
                "description": "Tick only what the model really supports. Use the “Test model” action to verify.",
                "fields": [
                    ("supports_structured_output", "structured_output_method"),
                    ("supports_tool_calling", "supports_parallel_tool_calls"),
                    "supports_vision",
                    ("supports_reasoning", "reasoning_control", "reasoning_disables_sampling"),
                ],
            },
        ),
        ("Limits and cost", {"fields": [("context_window", "max_output_tokens"), "rpm_limit",
                                        ("input_cost_per_mtok", "output_cost_per_mtok")]}),
    ]  # fmt: skip

    @admin.display(description="Capabilities")
    def capability_flags(self, obj):
        return ", ".join(sorted(c.value for c in obj.capabilities)) or "text only"

    @admin.action(description="Test model (makes real API calls)")
    def test_model(self, request, queryset):
        for llm_model in queryset.select_related("provider")[:5]:
            for result in ModelProber().probe(llm_model):
                level = messages.SUCCESS if result.ok else messages.ERROR
                self.message_user(
                    request,
                    f"{llm_model} · {result.capability}: {'passed' if result.ok else 'FAILED'} "
                    f"in {result.latency_ms} ms · {result.detail}",
                    level,
                )


class BindingInline(admin.TabularInline):
    model = NodeModelBinding
    formfield_overrides = COMPACT_JSON
    extra = 0
    ordering = ["priority"]
    autocomplete_fields = ["model"]
    fields = [
        "priority",
        "model",
        "is_enabled",
        "reasoning_effort",
        "max_retries",
        "params_override",
        "effective",
        "issues",
    ]
    readonly_fields = ["effective", "issues"]

    @admin.display(description="Effective params")
    def effective(self, obj):
        if not obj.pk:
            return "–"
        merged = {**obj.model.default_params, **obj.node.params_override, **obj.params_override}
        effort = obj.reasoning_effort or obj.node.reasoning_effort
        reasoning = effort if obj.model.supports_reasoning else "n/a"
        return format_html("<code>{}</code><br>reasoning: {}", json.dumps(merged), reasoning)

    @admin.display(description="Problems")
    def issues(self, obj):
        if not obj.pk:
            return "–"
        problems = obj.problems()
        if not problems:
            return _yes_no(True, yes="✔ ok")
        return format_html_join("", '<div style="color:#dc2626">{}</div>', ((p,) for p in problems))


@admin.register(NodeConfig)
class NodeConfigAdmin(admin.ModelAdmin):
    formfield_overrides = COMPACT_JSON
    list_display = ["node_key", "stage", "is_enabled", "reasoning_effort", "chain", "health"]
    list_filter = ["is_enabled"]
    inlines = [BindingInline]
    readonly_fields = ["node_key", "requirements"]
    fields = [
        "node_key",
        "requirements",
        "is_enabled",
        "reasoning_effort",
        "max_attempts",
        "max_tool_steps",
        "timeout_s",
        "params_override",
    ]
    actions = [export_json]

    def has_add_permission(self, request):
        return False  # one row per NodeSpec, created automatically

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("bindings__model__provider")

    @admin.display(description="Stage")
    def stage(self, obj):
        return obj.spec.stage.value

    @admin.display(description="Requirements")
    def requirements(self, obj):
        spec = obj.spec
        needs = ", ".join(sorted(c.value for c in spec.requires)) or "none"
        return format_html(
            "{}<br><b>Output:</b> {} {} · <b>Needs:</b> {} · <b>Min output:</b> {} tokens · <b>Min context:</b> {}"
            " · {}",
            spec.description,
            spec.output.value,
            f"({spec.schema_name})" if spec.schema_name else "",
            needs,
            spec.min_output_tokens,
            spec.min_context,
            "optional" if spec.optional else "required",
        )

    @admin.display(description="Model chain")
    def chain(self, obj):
        bindings = sorted(obj.bindings.all(), key=lambda b: b.priority)
        return " → ".join(str(b.model) for b in bindings if b.is_enabled) or "–"

    @admin.display(description="OK?")
    def health(self, obj):
        usable = [b for b in obj.bindings.all() if b.is_enabled and b.model.is_enabled and not b.problems()]
        if not obj.is_enabled:
            return "off"
        return _yes_no(bool(usable), no="✘ no usable model")


@admin.register(ModelCall)
class ModelCallAdmin(admin.ModelAdmin):
    list_display = ["created_at", "node_key", "provider_key", "model_name", "status", "attempt", "fallback_index",
                    "latency_ms", "input_tokens", "output_tokens", "cost"]  # fmt: skip
    list_filter = ["status", "node_key", "provider_key", "model_name"]
    date_hierarchy = "created_at"
    search_fields = ["error", "lesson_id", "run_id"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

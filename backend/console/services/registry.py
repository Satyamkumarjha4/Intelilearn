"""Providers and models, edited from the console (the Django admin's job until now).

Validation is the models' own (`full_clean`, which runs `clean()`), so the console refuses what the admin refuses.
Every change and its audit entry are saved together. Nothing here reads or returns an API key: a provider is the *name*
of the variable that holds its key, and whether that variable is set.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, DecimalField, OuterRef, ProtectedError, QuerySet, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from console.audit import AuditTrail
from console.errors import ModelInUse
from console.periods import Periods
from llm_registry.models import LLMModel, ModelCall, NodeModelBinding, Provider

from .probing import ProbeOutcome

#: model field → the name the API uses for it
API_NAMES = {"is_enabled": "enabled", "__all__": "non_field_errors"}


class ModelValidation:
    """Django's validation errors as the API's (field names the API uses, one list of messages each)."""

    def check(self, instance) -> None:
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise ValidationError(
                {API_NAMES.get(field, field): messages for field, messages in exc.message_dict.items()}
            ) from exc


class ProviderService:
    #: what an edit can change, and so what the audit trail keeps
    EDITABLE = {"rpm_limit": "rpm_limit", "base_url": "base_url", "enabled": "is_enabled"}

    def __init__(self, trail: AuditTrail, periods: Periods | None = None, validation: ModelValidation | None = None):
        self._trail, self._periods = trail, periods or Periods()
        self._validation = validation or ModelValidation()

    def listing(self) -> QuerySet[Provider]:
        """Providers with their model count and the spend of the last 7 days (the overview's 7d range), in one query."""
        period = self._periods.of("7d")
        spent = (
            ModelCall.objects.filter(
                provider_key=OuterRef("key"), created_at__gte=period.start, created_at__lte=period.end
            )
            .order_by()
            .values("provider_key")
            .annotate(total=Sum("cost"))
            .values("total")
        )
        return Provider.objects.annotate(
            models_count=Count("models", distinct=True),
            spend_7d=Coalesce(Subquery(spent), 0, output_field=DecimalField()),
        )

    def update(self, provider: Provider, changes: dict) -> Provider:
        before = self.snapshot(provider)
        for name, value in changes.items():
            setattr(provider, name, value)
        self._validation.check(provider)
        with transaction.atomic():
            provider.save()
            self._trail.record(
                "provider.update", "provider", provider.key, before=before, after=self.snapshot(provider)
            )
        return self.listing().get(pk=provider.pk)

    def snapshot(self, provider: Provider) -> dict:
        return {api: getattr(provider, attr) for api, attr in self.EDITABLE.items()}


class ModelService:
    def __init__(self, trail: AuditTrail, validation: ModelValidation | None = None):
        self._trail = trail
        self._validation = validation or ModelValidation()

    @staticmethod
    def listing() -> QuerySet[LLMModel]:
        return LLMModel.objects.select_related("provider").prefetch_related("bindings__node")

    def create(self, fields: dict) -> LLMModel:
        model = LLMModel(**fields)
        self._validation.check(model)
        with transaction.atomic():
            model.save()
            self._trail.record("model.create", "model", model.id, after=self.snapshot(model))
        return self.listing().get(pk=model.pk)

    def update(self, model: LLMModel, changes: dict) -> LLMModel:
        before = self.snapshot(model)
        for name, value in changes.items():
            setattr(model, name, value)
        self._validation.check(model)
        with transaction.atomic():
            model.save()
            self._trail.record("model.update", "model", model.id, before=before, after=self.snapshot(model))
        return self.listing().get(pk=model.pk)

    def delete(self, model: LLMModel) -> None:
        """Refused (`ModelInUse`, naming the steps) while a step binds the model: the binding's key protects it."""
        before, label = self.snapshot(model), str(model)
        try:
            with transaction.atomic():
                model.delete()
                self._trail.record("model.delete", "model", before["id"], before=before)
        except ProtectedError as exc:
            bound = NodeModelBinding.objects.filter(pk__in=[b.pk for b in exc.protected_objects])
            raise ModelInUse(label, sorted(bound.values_list("node__node_key", flat=True).distinct())) from exc

    def record_probe(self, model: LLMModel, outcome: ProbeOutcome) -> LLMModel:
        """Keep the result of a test on the model (without touching the routing cache) and note it in the trail."""
        before = self.last_probe(model)
        LLMModel.objects.filter(pk=model.pk).update(
            last_probe_at=timezone.now(),
            last_probe_ok=outcome.ok,
            last_probe_latency_s=outcome.latency_s,
            last_probe_error=outcome.error or "",
        )
        model.refresh_from_db()
        self._trail.record("model.probe", "model", model.id, before=before, after=self.last_probe(model))
        return model

    @staticmethod
    def last_probe(model: LLMModel) -> dict | None:
        if model.last_probe_at is None:
            return None
        return {
            "at": model.last_probe_at,
            "ok": model.last_probe_ok,
            "latency_s": model.last_probe_latency_s,
            "error": model.last_probe_error,
        }

    #: the fields the audit trail keeps of a model: its configuration, under the names the API uses
    CONFIG_FIELDS = [
        "name", "label", "default_params", "supports_structured_output", "structured_output_method",
        "supports_tool_calling", "supports_parallel_tool_calls", "supports_vision", "supports_reasoning",
        "reasoning_control", "reasoning_disables_sampling", "context_window", "max_output_tokens", "rpm_limit",
        "input_cost_per_mtok", "output_cost_per_mtok",
    ]  # fmt: skip

    def snapshot(self, model: LLMModel) -> dict:
        return {
            "id": model.id,
            "provider": model.provider.key,
            "enabled": model.is_enabled,
            **{name: getattr(model, name) for name in self.CONFIG_FIELDS},
        }

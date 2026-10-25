"""The lesson settings (`FlowSettings`), edited from the console with the Django admin's own validation.

The admin builds a model form for `FlowSettings`; so does this, so a value is accepted here exactly when the admin would
accept it. Lessons snapshot the settings when they start, so a change only reaches lessons started after it.
"""

from django.db import transaction
from django.forms import modelform_factory
from rest_framework.exceptions import ValidationError

from console.audit import AuditTrail
from graph.grading import RoutingPolicy
from lessons.models import FlowSettings

AdminForm = modelform_factory(FlowSettings, fields="__all__")


class FlowSettingsService:
    def __init__(self, trail: AuditTrail, policy: RoutingPolicy | None = None):
        self._trail, self._policy = trail, policy or RoutingPolicy()

    def current(self) -> dict:
        return self.present(FlowSettings.load())

    def present(self, settings: FlowSettings) -> dict:
        values = settings.snapshot()
        return {**values, "routing_thresholds": self._policy.thresholds(values)}

    def update(self, changes: dict) -> dict:
        settings = FlowSettings.load()
        before = settings.snapshot()
        form = AdminForm({**before, **changes}, instance=settings)
        if not form.is_valid():
            raise ValidationError({field: [str(m) for m in errors] for field, errors in form.errors.items()})
        with transaction.atomic():
            saved = form.save()
            self._trail.record("flow_settings.update", "flow_settings", saved.pk, before=before, after=saved.snapshot())
        return self.present(saved)

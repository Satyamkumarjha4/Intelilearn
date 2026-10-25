from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from console.serializers import FlowSettingsInputSerializer, FlowSettingsSerializer
from console.services.flow_settings import FlowSettingsService

from .base import CONSOLE_TAG, ConsoleView


class FlowSettingsView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Lesson settings",
        description=(
            "How quick checks, lessons and quality checks behave, with `routing_thresholds`: what the settings mean "
            "for where a score sends a learner. Each lesson keeps the settings it started with."
        ),
        responses={200: FlowSettingsSerializer},
    )
    def get(self, request):
        return Response(FlowSettingsSerializer(FlowSettingsService(self.audit).current()).data)

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Change the lesson settings",
        description=(
            "Any subset of the fields. Validated exactly like the Django admin's form, and applied to lessons started "
            "after the change. Nothing is saved if any value is refused."
        ),
        request=FlowSettingsInputSerializer,
        responses={200: FlowSettingsSerializer},
    )
    def patch(self, request):
        changes = FlowSettingsInputSerializer(data=request.data, partial=True)
        changes.is_valid(raise_exception=True)
        updated = FlowSettingsService(self.audit).update(changes.validated_data)
        return Response(FlowSettingsSerializer(updated).data)

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .health import HealthService

_component = inline_serializer(
    "HealthComponent",
    {"ok": serializers.BooleanField(), "latency_ms": serializers.IntegerField(), "detail": serializers.CharField()},
)


class HealthView(APIView):
    """Reports whether the API can reach Postgres (Supabase), Redis and at least one Celery worker."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["system"],
        summary="Service health",
        responses=inline_serializer(
            "Health",
            {
                "status": serializers.ChoiceField(choices=["ok", "degraded"]),
                "database": _component,
                "redis": _component,
                "celery": _component,
            },
        ),
    )
    def get(self, request):
        report = HealthService().report()
        return Response(report.to_dict(), status=200 if report.ok else 503)

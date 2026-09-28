import time

import redis
from django.conf import settings
from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.celery import app as celery_app


def _check(fn) -> dict:
    started = time.perf_counter()
    try:
        detail = fn()
        return {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000), "detail": detail}
    except Exception as exc:  # health checks report failures instead of raising
        return {"ok": False, "latency_ms": round((time.perf_counter() - started) * 1000), "detail": str(exc)}


def _database():
    with connection.cursor() as cursor:
        cursor.execute("select version()")
        return cursor.fetchone()[0].split(",")[0]


def _redis():
    client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
    return f"redis {client.info('server')['redis_version']}"


def _celery():
    replies = celery_app.control.ping(timeout=1.0)
    if not replies:
        raise RuntimeError("no workers responded")
    return f"{len(replies)} worker(s)"


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
        checks = {"database": _check(_database), "redis": _check(_redis), "celery": _check(_celery)}
        status = "ok" if all(c["ok"] for c in checks.values()) else "degraded"
        return Response({"status": status, **checks}, status=200 if status == "ok" else 503)

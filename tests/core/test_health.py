"""Unit under test: `core.health` (one HealthCheck per dependency, aggregated by HealthService) and the
`GET /api/health` view that reports it.

Why: the health endpoint is how you see that the API can reach Postgres, Redis and a Celery worker. It must report a
failing dependency (503 "degraded") with the reason, never crash because one of them is down.

Use cases:
- all dependencies up: 200 "ok" with each component's detail
- Redis down: 503 "degraded" with the error as the detail
- a check that raises is a failed result with its message and latency, not an exception
- the overall status is the worst component's
- the celery check fails when no worker answers
- the celery check can say how many workers answered (the console's overview)
- the OpenAPI schema lists /api/health
"""

from unittest.mock import patch

import pytest
from django.urls import reverse

from core.health import CeleryHealthCheck, HealthCheck, HealthService, RedisHealthCheck


class FakeCheck(HealthCheck):
    def __init__(self, name, detail="fine", error=None):
        self.name, self._detail, self._error = name, detail, error

    def probe(self):
        if self._error:
            raise self._error
        return self._detail


@pytest.mark.django_db
def test_health_ok(client):
    with (
        patch.object(RedisHealthCheck, "probe", return_value="redis 7"),
        patch.object(CeleryHealthCheck, "probe", return_value="1 worker(s)"),
    ):
        response = client.get(reverse("health"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["redis"]["detail"] == "redis 7"


@pytest.mark.django_db
def test_health_degraded_when_redis_down(client):
    with (
        patch.object(RedisHealthCheck, "probe", side_effect=ConnectionError("refused")),
        patch.object(CeleryHealthCheck, "probe", return_value="1 worker(s)"),
    ):
        response = client.get(reverse("health"))

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["redis"]["ok"] is False
    assert body["redis"]["detail"] == "refused"


def test_a_failing_check_is_a_result_not_an_exception():
    result = FakeCheck("redis", error=ConnectionError("refused")).run()

    assert (result.ok, result.detail) == (False, "refused")
    assert result.latency_ms >= 0


def test_overall_status_is_the_worst_component():
    healthy = HealthService([FakeCheck("a"), FakeCheck("b")]).report()
    degraded = HealthService([FakeCheck("a"), FakeCheck("b", error=RuntimeError("down"))]).report()

    assert (healthy.ok, healthy.status) == (True, "ok")
    assert (degraded.ok, degraded.status) == (False, "degraded")
    assert degraded.to_dict()["b"] == {"ok": False, "latency_ms": degraded.components["b"].latency_ms, "detail": "down"}


def test_celery_check_fails_when_no_worker_answers():
    class Control:
        def ping(self, timeout):
            return []

    class App:
        control = Control()

    result = CeleryHealthCheck(app=App()).run()

    assert (result.ok, result.detail) == (False, "no workers responded")


def test_celery_check_counts_the_workers_that_answered():
    class Control:
        def ping(self, timeout):
            return [{"worker-1": {"ok": "pong"}}, {"worker-2": {"ok": "pong"}}]

    class App:
        control = Control()

    check = CeleryHealthCheck(app=App())

    assert check.worker_count() == 2
    assert check.run().detail == "2 worker(s)"


def test_openapi_schema_lists_health(client):
    response = client.get(reverse("schema"), HTTP_ACCEPT="application/json")

    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]

from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_ok(client):
    with (
        patch("core.views._redis", return_value="redis 7"),
        patch("core.views._celery", return_value="1 worker(s)"),
    ):
        response = client.get(reverse("health"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True


@pytest.mark.django_db
def test_health_degraded_when_redis_down(client):
    with (
        patch("core.views._redis", side_effect=ConnectionError("refused")),
        patch("core.views._celery", return_value="1 worker(s)"),
    ):
        response = client.get(reverse("health"))

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["redis"]["ok"] is False
    assert body["redis"]["detail"] == "refused"


def test_openapi_schema_lists_health(client):
    response = client.get(reverse("schema"), HTTP_ACCEPT="application/json")

    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]

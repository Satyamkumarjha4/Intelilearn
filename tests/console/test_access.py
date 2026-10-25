"""Unit under test: `console.access` (`ConsolePermission`, `ConsoleRateThrottle`), `console.views.base` and the schema
of the whole `/api/console/` API.

Why: the console can re-route every lesson and see every learner. Only staff may use it, and nobody else may even learn
that it exists. It has to stay usable when something loops, and every endpoint has to be in the API documentation.

Use cases:
- staff get a 200 from every read endpoint; anyone not signed in, and any learner, get the same 404 as a page that does
  not exist, on every read and every write, and nothing is changed
- a bad or expired token is a 401, so the browser's silent refresh can run
- a staff member is limited to 120 requests a minute (`CONSOLE_THROTTLE_RATE`) each; refused requests do not use it up
- no response may be cached by a browser or a proxy
- the API schema lists every console endpoint under the "console" tag, and generates without a warning
- the current user says whether they are staff (so a screen can offer the console)
- a console write sent with the session cookie but without the CSRF header is refused with a 403 and changes nothing;
  with the header it goes through (the cookie alone must never be enough to act as staff)
"""

import io
from contextlib import redirect_stderr

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from accounts.models import User
from console.access import ConsoleRateThrottle
from lessons.models import GraphRun, Lesson

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"
HEALTH = {"ok": True, "latency_ms": 1, "detail": "fine"}


class FakeHealth:
    def report(self):
        return {"status": "ok", "database": HEALTH, "redis": HEALTH, "celery": HEALTH, "workers": 1}


@pytest.fixture
def routes(registry, lesson, monkeypatch):
    """Every console endpoint with a real target: (method, path, body)."""
    from console.views.overview import OverviewView

    monkeypatch.setattr(OverviewView, "health", FakeHealth())
    run = GraphRun.objects.create(lesson=lesson, status="running", trigger="start")
    model = registry.models["lite"]
    node = {"enabled": True, "reasoning_effort": "low", "max_attempts": 2, "timeout_s": 60, "bindings": []}
    return [
        ("get", "/api/console/overview", None),
        ("get", "/api/console/usage", None),
        ("get", "/api/console/usage/export.csv", None),
        ("get", "/api/console/runs", None),
        ("get", f"/api/console/runs/{run.id}", None),
        ("post", f"/api/console/runs/{run.id}/retry", None),
        ("post", f"/api/console/runs/{run.id}/cancel", None),
        ("get", "/api/console/providers", None),
        ("patch", "/api/console/providers/gemini", {"rpm_limit": 3}),
        ("get", "/api/console/models", None),
        ("post", "/api/console/models", {"provider": "groq", "name": "new-model"}),
        ("patch", f"/api/console/models/{model.id}", {"label": "x"}),
        ("delete", f"/api/console/models/{model.id}", None),
        ("post", f"/api/console/models/{model.id}/probe", None),
        ("get", "/api/console/nodes", None),
        ("put", "/api/console/nodes/diagnostic.review", node | {"enabled": False}),
        ("get", "/api/console/profiles", None),
        ("post", "/api/console/profiles/cheap/preview", None),
        ("get", "/api/console/flow-settings", None),
        ("patch", "/api/console/flow-settings", {"final_test_min": 9}),
        ("get", "/api/console/learners", None),
        ("get", "/api/console/audit", None),
    ]


def call(client, method, path, body):
    return getattr(client, method)(path, body, format="json") if body is not None else getattr(client, method)(path)


def test_staff_can_read_every_read_endpoint(staff_client, routes):
    for method, path, body in routes:
        if method == "get":
            assert call(staff_client, method, path, body).status_code == 200, path


@pytest.mark.parametrize("who", ["anonymous", "learner"])
def test_anyone_else_gets_a_404_on_every_endpoint_and_nothing_changes(who, api_client, learner_client, routes):
    from console.models import AuditEntry
    from llm_registry.models import LLMModel, Provider

    client = api_client if who == "anonymous" else learner_client
    if who == "learner":
        client.get("/api/auth/csrf")  # a learner's writes pass CSRF like any, then meet the 404
    models, providers = list(LLMModel.objects.values()), list(Provider.objects.values())

    for method, path, body in routes:
        response = call(client, method, path, body)
        assert response.status_code == 404, (method, path)
        assert response.json() == {"detail": "Not found.", "code": "not_found"}

    assert list(LLMModel.objects.values()) == models and list(Provider.objects.values()) == providers
    assert not AuditEntry.objects.exists()


def test_a_missing_console_page_and_a_forbidden_one_look_the_same(staff_client, learner_client, api_client):
    missing = staff_client.get("/api/console/runs/00000000-0000-0000-0000-000000000000").json()
    hidden = api_client.get("/api/console/overview").json()

    assert missing == hidden


def test_a_bad_token_is_a_401_so_the_browser_can_refresh_and_retry(api_client):
    api_client.cookies["lc_access"] = "not-a-token"

    response = api_client.get("/api/console/overview")

    assert response.status_code == 401


def test_a_staff_member_is_limited_per_minute_and_others_are_not_affected(routes, staff_user, monkeypatch):
    monkeypatch.setattr(ConsoleRateThrottle, "THROTTLE_RATES", {"console": "3/min"})
    other_staff = User.objects.create_user(
        "two@example.com", password="correct-horse-battery-staple", name="Two", is_staff=True
    )

    def signed_in(user):
        client = APIClient()
        client.post("/api/auth/login", {"email": user.email, "password": "correct-horse-battery-staple"}, format="json")
        return client

    first, second = signed_in(staff_user), signed_in(other_staff)

    statuses = [first.get("/api/console/providers").status_code for _ in range(5)]
    assert statuses == [200, 200, 200, 429, 429]
    assert second.get("/api/console/providers").status_code == 200
    assert first.get("/api/console/providers").json()["code"] == "throttled"


def test_requests_that_were_refused_as_not_found_do_not_use_up_the_limit(routes, learner_client, monkeypatch):
    monkeypatch.setattr(ConsoleRateThrottle, "THROTTLE_RATES", {"console": "2/min"})

    assert {learner_client.get("/api/console/providers").status_code for _ in range(6)} == {404}


def test_the_limit_is_120_a_minute_unless_the_environment_says_otherwise(settings):
    throttle = ConsoleRateThrottle()

    assert throttle.scope == "console" and (throttle.num_requests, throttle.duration) == (120, 60)
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["console"] == "120/min"


def test_no_response_may_be_cached(staff_client, learner_client, routes):
    assert staff_client.get("/api/console/providers")["Cache-Control"] == "no-store"
    assert staff_client.get("/api/console/runs/not-a-uuid")["Cache-Control"] == "no-store"
    assert learner_client.get("/api/console/providers")["Cache-Control"] == "no-store"


CONSOLE_PATHS = {
    "/api/console/overview", "/api/console/usage", "/api/console/usage/export.csv", "/api/console/runs",
    "/api/console/runs/{run_id}", "/api/console/runs/{run_id}/retry", "/api/console/runs/{run_id}/cancel",
    "/api/console/providers", "/api/console/providers/{key}", "/api/console/models",
    "/api/console/models/{model_id}", "/api/console/models/{model_id}/probe", "/api/console/nodes",
    "/api/console/nodes/{key}", "/api/console/profiles", "/api/console/profiles/{name}/preview",
    "/api/console/flow-settings", "/api/console/learners", "/api/console/audit",
}  # fmt: skip


def test_the_schema_lists_every_console_endpoint_under_the_console_tag(staff_client):
    schema = staff_client.get("/api/schema", HTTP_ACCEPT="application/json").json()

    console = {path: item for path, item in schema["paths"].items() if path.startswith("/api/console/")}
    assert set(console) == CONSOLE_PATHS
    methods = ("get", "post", "put", "patch", "delete")
    operations = [op for item in console.values() for method, op in item.items() if method in methods]
    assert operations and all(op["tags"] == ["console"] for op in operations)
    assert all(op.get("summary") and op.get("responses") for op in operations)


def test_the_schema_generates_without_a_warning():
    errors = io.StringIO()

    with redirect_stderr(errors):
        call_command("spectacular", "--validate", "--fail-on-warn", "--file", "/dev/null")

    assert errors.getvalue() == ""


def test_the_current_user_says_whether_they_are_staff(staff_client, learner_client):
    assert staff_client.get("/api/auth/me").json()["is_staff"] is True


def make_lesson_row():
    return Lesson.objects.create(
        owner=User.objects.create_user("owner@example.com", password="x" * 12), topic="Binary search"
    )


def test_a_console_write_needs_the_csrf_header_as_well_as_the_session_cookie(staff_user):
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/auth/csrf")
    token = client.cookies["csrftoken"].value
    client.post(
        "/api/auth/login", {"email": staff_user.email, "password": PASSWORD}, format="json", HTTP_X_CSRFTOKEN=token
    )
    lesson = make_lesson_row()
    run = GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.RUNNING)

    without = client.post(f"/api/console/runs/{run.id}/cancel")
    run.refresh_from_db()
    assert without.status_code == 403 and run.status == GraphRun.Status.RUNNING  # nothing was cancelled

    with_token = client.post(f"/api/console/runs/{run.id}/cancel", HTTP_X_CSRFTOKEN=token)
    run.refresh_from_db()
    assert with_token.status_code == 202 and run.status == GraphRun.Status.CANCELLED

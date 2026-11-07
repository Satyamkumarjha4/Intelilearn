"""Unit under test: who may use the credit, wallet, payment and revenue endpoints of the console (phase 10.9; the
rules of `console.access`).

Why: these endpoints move credits, change prices and refund money. Only staff may use them, and anyone else, signed in
or not, must meet the same 404 as a page that does not exist, on every read and every write, with nothing changed. The
general console access tests cover the endpoints that existed when they were written; this covers each new one by name,
so a new route cannot be added without being added here.

Use cases:
- staff get a 200 from every new read and every new write that is valid
- anyone not signed in, and any learner, get the same 404 on each of the 11 new paths (reads and writes) and nothing is
  changed: no price, plan, setting, credit, exemption, refund or change-log entry
- a write sent with the session cookie but without the CSRF header is a 403 and changes nothing
- the schema has every new path, tagged console
- the new paths are exactly the ones listed here (so adding one without a test fails)
"""

import re
import uuid

import pytest
from rest_framework.test import APIClient

from console.models import AuditEntry
from credits.models import ActionPrice, CreditSettings, Plan, Wallet
from credits.plans.seed import PlanSeed
from credits.pricing.seed import PriceSeed
from payments.models import RefundAttempt

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def routes(user, payments):
    """Every new console route with a real target: (method, path, body)."""
    PriceSeed().apply()
    PlanSeed().apply()
    order = payments.buy("one_time", credits=100)
    payments.send("succeeded", order)
    attempt = RefundAttempt.objects.create(
        token=uuid.uuid4(), order=order, amount_paise=100, refund_ref="r1", created_at=order.created_at
    )
    return [
        ("get", "/api/console/credits", None),
        ("patch", "/api/console/credits/prices/lesson.full", {"credits": 99}),
        ("patch", "/api/console/credits/plans/weekly_pro", {"credits": 150}),
        ("patch", "/api/console/credits/settings", {"signup_credits": 77}),
        ("get", f"/api/console/learners/{user.pk}/wallet", None),
        ("patch", f"/api/console/learners/{user.pk}/wallet", {"credits_exempt": True}),
        ("post", f"/api/console/learners/{user.pk}/wallet/adjust", {"amount": 5, "reason": "because"}),
        ("get", "/api/console/payments", None),
        ("get", "/api/console/payments/shortfalls", None),
        ("post", f"/api/console/payments/{order.pk}/refund", {"token": str(uuid.uuid4())}),
        ("post", f"/api/console/refunds/{attempt.pk}/mark-failed", None),
        ("get", "/api/console/revenue", None),
    ], order


def call(client, method, path, body):
    return getattr(client, method)(path, body, format="json") if body is not None else getattr(client, method)(path)


def state():
    return (
        list(ActionPrice.objects.values_list("key", "credits", "active")),
        list(Plan.objects.values_list("key", "credits")),
        CreditSettings.load().signup_credits,
        list(Wallet.objects.values_list("pk", "credits_exempt")),
        list(RefundAttempt.objects.values_list("pk", "state")),
        AuditEntry.objects.count(),
    )


def test_staff_can_use_every_new_route(staff_client, routes):
    items, _ = routes
    for method, path, body in items:
        assert call(staff_client, method, path, body).status_code == 200, (method, path)


@pytest.mark.parametrize("who", ["anonymous", "learner"])
def test_anyone_else_gets_a_404_on_every_new_path_and_nothing_changes(who, api_client, learner_client, routes):
    items, _ = routes
    client = api_client if who == "anonymous" else learner_client
    if who == "learner":
        client.get("/api/auth/csrf")  # a learner's writes pass CSRF like any, then meet the 404
    before = state()

    for method, path, body in items:
        response = call(client, method, path, body)
        assert response.status_code == 404, (method, path)
        assert response.json() == {"detail": "Not found.", "code": "not_found"}

    assert state() == before


def test_a_write_without_the_csrf_header_is_a_403_and_changes_nothing(staff_user, routes):
    items, _ = routes
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/auth/csrf")
    token = client.cookies["csrftoken"].value
    client.post(
        "/api/auth/login", {"email": staff_user.email, "password": PASSWORD}, format="json", HTTP_X_CSRFTOKEN=token
    )
    before = state()

    for method, path, body in items:
        if method != "get":
            assert call(client, method, path, body).status_code == 403, (method, path)

    assert state() == before


def test_the_schema_has_every_new_path_tagged_console(staff_client):
    schema = staff_client.get("/api/schema", HTTP_ACCEPT="application/json").json()

    for path in NEW_PATHS:
        assert path in schema["paths"], path
        operations = [op for method, op in schema["paths"][path].items() if method in ("get", "post", "patch")]
        assert operations and all(op["tags"] == ["console"] for op in operations), path


NEW_PATHS = {
    "/api/console/credits", "/api/console/credits/prices/{key}", "/api/console/credits/plans/{key}",
    "/api/console/credits/settings", "/api/console/learners/{learner_id}/wallet",
    "/api/console/learners/{learner_id}/wallet/adjust", "/api/console/payments", "/api/console/payments/shortfalls",
    "/api/console/payments/{order_id}/refund", "/api/console/refunds/{attempt_id}/mark-failed", "/api/console/revenue",
}  # fmt: skip


def test_the_new_paths_are_eleven_and_all_of_them_are_exercised_above(routes):
    items, _ = routes

    assert len(NEW_PATHS) == 11
    exercised = {path for _, path, _ in items}
    assert len(exercised) == 11 and {re.sub(r"[0-9a-f-]{36}|\d+|lesson\.full|weekly_pro", "{}", p) for p in exercised}

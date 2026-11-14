"""Unit under test: `console.audit.AuditTrail`, `console.models.AuditEntry` and `GET /api/console/audit`, with the
rule that every console endpoint that changes something writes an audit entry.

Why: the console lets a few people re-route every lesson Socra writes. The change log is how anyone finds out later who
changed what, so it must have an entry for every change, none for a change that was refused, nothing a secret can sit
in, and no way to edit or erase it from the API.

Use cases:
- an entry keeps who, what, the target and the target before and after, as plain JSON (ids, decimals and dates as text)
- the log lists newest first in pages, names the fields that changed, and keeps the actor's email after the account goes
- it can only be read: nothing writes, edits or deletes entries through the API, and a learner cannot read it
- every endpoint that changes something writes exactly one entry, with the action named for it (the credit, wallet,
  payment and testimonial endpoints included); reading, previewing a profile and refused requests write none
- a new endpoint that changes something cannot be added without being listed here (a guard over the URL configuration)
- the log is read in a fixed number of queries
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import get_resolver
from langchain_core.messages import AIMessage

from accounts.models import EmailLock, PendingSignup, User
from console.audit import AuditTrail
from console.models import AuditEntry
from credits.pricing.seed import PriceSeed
from lessons.models import GraphRun
from lessons.stages import Stage
from marketing.models import Testimonial
from payments.models import RefundAttempt

pytestmark = pytest.mark.django_db


def test_an_entry_keeps_who_what_and_the_target_before_and_after(staff_user, now):
    entry = AuditTrail(staff_user).record(
        "model.update",
        "model",
        7,
        before={"cost": Decimal("0.1500"), "id": uuid4(), "at": now},
        after={"cost": Decimal("0.2")},
    )

    entry.refresh_from_db()
    assert (entry.actor_id, entry.actor_email, entry.action, entry.target_type, entry.target_id) == (
        staff_user.id, "root@example.com", "model.update", "model", "7")  # fmt: skip
    assert entry.before["cost"] == "0.1500" and entry.before["at"] == "2026-03-15T12:00:00Z"
    assert isinstance(entry.before["id"], str) and entry.after == {"cost": "0.2"}
    assert entry.created_at == now


def test_a_creation_or_a_deletion_has_only_one_side(staff_user):
    created = AuditTrail(staff_user).record("model.create", "model", 1, after={"name": "x"})
    deleted = AuditTrail(staff_user).record("model.delete", "model", 1, before={"name": "x"})

    assert (created.before, created.after) == (None, {"name": "x"})
    assert (deleted.before, deleted.after) == ({"name": "x"}, None)


def test_the_log_is_newest_first_and_says_what_changed(staff_client, staff_user):
    trail = AuditTrail(staff_user)
    trail.record("provider.update", "provider", "groq", before={"rpm_limit": 30, "enabled": True},
                 after={"rpm_limit": 60, "enabled": True})  # fmt: skip
    trail.record("model.create", "model", 3, after={"name": "x", "label": ""})

    body = staff_client.get("/api/console/audit").json()

    assert [e["action"] for e in body["results"]] == ["model.create", "provider.update"]
    created, updated = body["results"]
    assert created["changed_fields"] == ["label", "name"] and updated["changed_fields"] == ["rpm_limit"]
    assert updated["actor"] == {"id": str(staff_user.id), "name": "Root Admin", "email": "root@example.com"}
    assert (updated["target_type"], updated["target_id"], updated["actor_email"]) == ("provider", "groq",
                                                                                      "root@example.com")  # fmt: skip
    assert updated["before"] == {"rpm_limit": 30, "enabled": True} and updated["created_at"].endswith("Z")


def test_the_log_is_paged_with_a_cursor(staff_client, staff_user):
    for index in range(5):
        AuditTrail(staff_user).record("model.update", "model", index)

    first = staff_client.get("/api/console/audit?page_size=2").json()
    second = staff_client.get(first["next"]).json()
    third = staff_client.get(second["next"]).json()

    assert [e["target_id"] for e in first["results"] + second["results"] + third["results"]] == [
        "4",
        "3",
        "2",
        "1",
        "0",
    ]
    assert third["next"] is None


def test_an_entry_outlives_the_account_that_made_it(staff_client, staff_user):
    other = User.objects.create_user("gone@example.com", password="x" * 12, name="Gone", is_staff=True)
    AuditTrail(other).record("model.update", "model", 1)

    other.delete()

    [entry] = staff_client.get("/api/console/audit").json()["results"]
    assert entry["actor"] is None and entry["actor_email"] == "gone@example.com"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_the_log_cannot_be_written_through_the_api(staff_client, staff_user, method):
    entry = AuditTrail(staff_user).record("model.update", "model", 1)

    assert getattr(staff_client, method)("/api/console/audit", {}, format="json").status_code == 405
    assert getattr(staff_client, method)(f"/api/console/audit/{entry.id}", {}, format="json").status_code == 404
    assert AuditEntry.objects.count() == 1


def test_a_learner_cannot_read_the_log(learner_client, staff_user):
    AuditTrail(staff_user).record("model.update", "model", 1)

    assert learner_client.get("/api/console/audit").status_code == 404


def test_the_log_query_count_does_not_grow_with_the_entries(staff_client, staff_user, count_queries):
    def fetch():
        assert staff_client.get("/api/console/audit?page_size=100").status_code == 200

    AuditTrail(staff_user).record("model.update", "model", 1, before={"a": 1}, after={"a": 2})
    few = count_queries(fetch)
    for index in range(30):
        AuditTrail(User.objects.create_user(f"s{index}@example.com", password="x" * 12, name="S")).record(
            "model.update", "model", index
        )

    assert count_queries(fetch) == few


# --- every change is on the log ---------------------------------------------------------------------------------------


class Chat:
    def invoke(self, messages):
        return AIMessage(content="pong")

    def with_structured_output(self, schema, method=None, include_raw=False):
        class Runnable:
            def invoke(self, messages):
                return {"raw": AIMessage(content=""), "parsed": schema(ok=True, word="pong"), "parsing_error": None}

        return Runnable()

    def bind_tools(self, tools):
        class Runnable:
            def invoke(self, messages):
                return AIMessage(content="", tool_calls=[{"name": "get_server_time", "args": {}, "id": "1"}])

        return Runnable()


@pytest.fixture
def changes(registry, make_lesson, queue, monkeypatch, user, other_user, payments, now, settings):
    """Each endpoint that changes something: (url name, method) → (action it must log, a call that makes the change)."""
    monkeypatch.setattr("llm_registry.providers.CHAT_MODEL_FACTORY", lambda model, timeout: Chat())
    failed_lesson = make_lesson(stage=Stage.FAILED, error="boom")
    failed_run = GraphRun.objects.create(lesson=failed_lesson, status="failed", trigger="start")
    running_run = GraphRun.objects.create(lesson=make_lesson(), status="running", trigger="start")
    registry.bind("lesson.plan", "flash")
    unused = registry.models["lite"]
    node_body = {"enabled": True, "reasoning_effort": "low", "max_attempts": 2, "timeout_s": 60,
                 "bindings": [{"model": registry.models["lite"].id}]}  # fmt: skip
    new_model = {"provider": "groq", "name": "openai/gpt-oss-20b", "supports_structured_output": True,
                 "context_window": 131_072, "max_output_tokens": 65_536}  # fmt: skip
    erased = other_user  # the learner the erasure endpoint is asked to erase
    PriceSeed().apply()
    order = payments.buy("one_time", credits=100)
    payments.send("succeeded", order)
    attempt = RefundAttempt.objects.create(
        token=uuid4(), order=order, amount_paise=100, refund_ref="r1", created_at=order.created_at
    )

    stuck = User.objects.create_user("stuck@example.com", password="correct-horse-battery-staple", name="Stuck")
    waiting = [  # sign-ups waiting for a code: one to resend to, one locked to unlock, one to approve
        PendingSignup.objects.create(
            email=f"wait{n}@example.com",
            email_canonical=f"wait{n}@example.com",
            name=f"Wait {n}",
            password_hash="x",
            terms_accepted_at=now,
            terms_version="1",
            expires_at=now + timedelta(hours=1),
        )  # fmt: skip
        for n in range(3)
    ]
    EmailLock.objects.create(  # the lock rules read the system clock, not the frozen `now`
        email_canonical="wait1@example.com", locked_until=datetime.now(UTC) + timedelta(minutes=30), strikes=3
    )
    settings.TURNSTILE_SITE_KEY, settings.TURNSTILE_SECRET_KEY = "site-key", "secret-key"

    first, second, third = (
        Testimonial.objects.create(name=n, context="Class 12 student", quote="q", position=i)
        for i, n in enumerate("ABC")
    )  # the reorder runs first, so its list is every one that exists

    def do(method, path, body=None):
        return lambda client: (
            getattr(client, method)(path, body, format="json") if body else getattr(client, method)(path)
        )

    return {
        ("console-run-retry", "post"): ("run.retry", do("post", f"/api/console/runs/{failed_run.id}/retry")),
        ("console-run-cancel", "post"): ("run.cancel", do("post", f"/api/console/runs/{running_run.id}/cancel")),
        ("console-provider", "patch"): (
            "provider.update",
            do("patch", "/api/console/providers/gemini", {"rpm_limit": 5}),
        ),
        ("console-models", "post"): ("model.create", do("post", "/api/console/models", new_model)),
        ("console-model", "patch"): ("model.update", do("patch", f"/api/console/models/{unused.id}", {"label": "x"})),
        ("console-model", "delete"): ("model.delete", do("delete", f"/api/console/models/{registry.models['oss'].id}")),
        ("console-model-probe", "post"): ("model.probe", do("post", f"/api/console/models/{unused.id}/probe")),
        ("console-node", "put"): ("node.update", do("put", "/api/console/nodes/lesson.plan", node_body)),
        ("console-flow-settings", "patch"): (
            "flow_settings.update",
            do("patch", "/api/console/flow-settings", {"alignment_max_rounds": 3}),
        ),
        ("console-credit-price", "patch"): (
            "credits.price",
            do("patch", "/api/console/credits/prices/lesson.full", {"credits": 11}),
        ),
        ("console-credit-plan", "patch"): (
            "credits.plan",
            do("patch", "/api/console/credits/plans/weekly_pro", {"credits": 120}),
        ),
        ("console-credit-settings", "patch"): (
            "credits.settings",
            do("patch", "/api/console/credits/settings", {"signup_credits": 31}),
        ),
        ("console-wallet", "patch"): (
            "credits.exempt",
            do("patch", f"/api/console/learners/{user.pk}/wallet", {"credits_exempt": True}),
        ),
        ("console-wallet-adjust", "post"): (
            "credits.adjust",
            do(
                "post",
                f"/api/console/learners/{user.pk}/wallet/adjust",
                {"amount": 5, "reason": "r", "token": str(uuid4())},
            ),
        ),
        ("console-payment-refund", "post"): (
            "payments.refund",
            do("post", f"/api/console/payments/{order.pk}/refund", {"token": str(uuid4())}),
        ),
        ("console-refund-failed", "post"): (
            "payments.refund_failed",
            do("post", f"/api/console/refunds/{attempt.pk}/mark-failed"),
        ),
        ("console-learner-erasure", "delete"): (
            "learner.erase",
            do("delete", f"/api/console/learners/{erased.pk}/erasure", {"confirm_email": erased.email}),
        ),
        ("console-testimonials-reorder", "post"): (
            "testimonial.reorder",
            do("post", "/api/console/testimonials/reorder", {"ids": [third.pk, second.pk, first.pk]}),
        ),
        ("console-testimonials", "post"): (
            "testimonial.create",
            do("post", "/api/console/testimonials", {"name": "D", "context": "Class 10 student", "quote": "q"}),
        ),
        ("console-testimonial", "patch"): (
            "testimonial.update",
            do("patch", f"/api/console/testimonials/{first.pk}", {"quote": "A new quote"}),
        ),
        ("console-testimonial", "delete"): (
            "testimonial.delete",
            do("delete", f"/api/console/testimonials/{second.pk}"),
        ),
        ("console-verification-resend", "post"): (
            "learner.verification_resent",
            do("post", f"/api/console/learners/{stuck.pk}/verification/resend"),
        ),
        ("console-verification-unlock", "post"): (
            "learner.verification_unlocked",
            do("post", f"/api/console/learners/{stuck.pk}/verification/unlock"),
        ),
        ("console-verification-mark", "post"): (
            "learner.verification_marked",
            do("post", f"/api/console/learners/{stuck.pk}/verification/mark-verified", {"reason": "Phoned the school"}),
        ),
        ("console-signup-resend", "post"): (
            "signup.resend",
            do("post", f"/api/console/signups/{waiting[0].pk}/resend"),
        ),
        ("console-signup-unlock", "post"): (
            "signup.unlock",
            do("post", f"/api/console/signups/{waiting[1].pk}/unlock"),
        ),
        ("console-signup-approve", "post"): (
            "signup.approved",
            do("post", f"/api/console/signups/{waiting[2].pk}/approve", {"reason": "Confirmed by phone"}),
        ),
        ("console-auth-settings", "put"): (
            "auth_settings.update",
            do("put", "/api/console/auth-settings", {"captcha_enabled": True}),
        ),
    }


NODE_OFF = {"enabled": True, "reasoning_effort": "low", "max_attempts": 2, "timeout_s": 5, "bindings": []}

#: endpoints that use POST (or another writing method) but change nothing
CHANGE_FREE = {("console-profile-preview", "post")}


def test_every_endpoint_that_changes_something_writes_exactly_one_entry(staff_client, staff_user, changes):
    for (name, _), (action, make_change) in changes.items():
        before = AuditEntry.objects.count()

        response = make_change(staff_client)

        assert response.status_code < 400, (name, response.content)
        assert AuditEntry.objects.count() == before + 1, name
        entry = AuditEntry.objects.latest("id")
        assert (entry.action, entry.actor_id) == (action, staff_user.id), name


def test_no_entry_is_written_when_a_request_is_refused(staff_client, changes):
    refused = [
        lambda c: c.post("/api/console/models", {"provider": "nobody"}, format="json"),
        lambda c: c.patch("/api/console/providers/gemini", {"rpm_limit": 0}, format="json"),
        lambda c: c.patch("/api/console/flow-settings", {"alignment_min_score": 99}, format="json"),
        lambda c: c.put("/api/console/nodes/learner.assess", {**NODE_OFF, "enabled": False}, format="json"),
        lambda c: c.post("/api/console/runs/00000000-0000-0000-0000-000000000000/cancel"),
        lambda c: c.post("/api/console/learners/00000000-0000-0000-0000-000000000000/verification/resend"),
        lambda c: c.post("/api/console/signups/00000000-0000-0000-0000-000000000000/approve", {"reason": "A reason"}),
        lambda c: c.put("/api/console/auth-settings", {}, format="json"),
    ]  # fmt: skip

    for attempt in refused:
        assert attempt(staff_client).status_code >= 400

    assert not AuditEntry.objects.exists()


def test_reading_and_previewing_write_nothing(staff_client, changes, monkeypatch):
    from console.views.overview import OverviewView

    class Health:
        def report(self):
            up = {"ok": True, "latency_ms": 1, "detail": "fine"}
            return {"status": "ok", "database": up, "redis": up, "celery": up, "workers": 1}

    monkeypatch.setattr(OverviewView, "health", Health())
    for path in ("overview", "usage", "usage/export.csv", "runs", "providers", "models", "nodes", "profiles",
                 "flow-settings", "learners", "audit", "signups", "abuse", "auth-settings"):  # fmt: skip
        response = staff_client.get(f"/api/console/{path}")
        b"".join(response.streaming_content) if response.streaming else None
        assert response.status_code == 200, path
    assert staff_client.post("/api/console/profiles/cheap/preview").status_code == 200

    assert not AuditEntry.objects.exists()


def test_the_changes_listed_here_are_every_endpoint_that_can_change_something(changes):
    """A guard: add an endpoint that writes and this fails until the endpoint has an audit test above."""
    found = set()
    for pattern in get_resolver().url_patterns:
        if getattr(pattern, "namespace", None) is None and "console/" in str(pattern.pattern):
            for route in pattern.url_patterns:
                view = route.callback.view_class
                for method in ("post", "put", "patch", "delete"):
                    if hasattr(view, method):
                        found.add((route.name, method))

    assert found == set(changes) | CHANGE_FREE

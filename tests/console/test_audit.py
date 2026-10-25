"""Unit under test: `console.audit.AuditTrail`, `console.models.AuditEntry` and `GET /api/console/audit`, with the
rule that every console endpoint that changes something writes an audit entry.

Why: the console lets a few people re-route every lesson Socra writes. The change log is how anyone finds out later who
changed what, so it must have an entry for every change, none for a change that was refused, nothing a secret can sit
in, and no way to edit or erase it from the API.

Use cases:
- an entry keeps who, what, the target and the target before and after, as plain JSON (ids, decimals and dates as text)
- the log lists newest first in pages, names the fields that changed, and keeps the actor's email after the account goes
- it can only be read: nothing writes, edits or deletes entries through the API, and a learner cannot read it
- every endpoint that changes something writes exactly one entry, with the action named for it; reading, previewing a
  profile and refused requests write none
- a new endpoint that changes something cannot be added without being listed here (a guard over the URL configuration)
- the log is read in a fixed number of queries
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import get_resolver
from langchain_core.messages import AIMessage

from accounts.models import User
from console.audit import AuditTrail
from console.models import AuditEntry
from lessons.models import GraphRun
from lessons.stages import Stage

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
def changes(registry, make_lesson, queue, monkeypatch):
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
            do("patch", "/api/console/flow-settings", {"final_test_min": 9}),
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
                 "flow-settings", "learners", "audit"):  # fmt: skip
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

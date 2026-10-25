"""Unit under test: `console.services.registry` (`ProviderService`, `ModelService`) and `console.services.probing`
(`ModelProbeService`), behind `/api/console/providers` and `/api/console/models`.

Why: this is where the model registry is edited from a screen instead of the Django admin. It must show which keys are
set without ever showing a key, refuse the same bad input the admin refuses (a parameter a provider rejects, a base URL
on a vendor that takes none), never delete a model a step still uses, and say plainly whether a model works.

Use cases:
- providers list their key variable's *name* and whether it is set, never its value; with models count and 7-day spend
- a provider's rate limit, base URL and enabled flag can be changed (and cleared); nothing else about it can, and the
  admin's rules for a base URL hold; a refused change leaves it alone
- models list with capabilities, limits, prices, the steps they use and the last test, in a fixed number of queries
- a model can be added and changed with the admin's validation (unique per provider, parameters the vendor accepts,
  reasoning needs a control), and its provider cannot be moved
- a model bound to a step cannot be deleted: 409 naming the steps, nothing changed; an unbound one is deleted
- testing a model runs the capability probes it claims within 20 seconds, stores the result on it, and says
  {ok, latency_s, error}; a failing model, a missing key and a probe that runs out of time all report instead of raising
- the test calls are made with the registry's real chat factory unless one is injected, and an error never carries a key
- every change is audited with the model as it was and as it became, and no secret ends up in a response or the log
"""

from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage

from console.models import AuditEntry
from console.services.probing import ModelProbeService
from llm_registry.models import LLMModel, Provider

pytestmark = pytest.mark.django_db

H = timedelta(hours=1)
D = timedelta(days=1)
SECRETS = ("gemini-secret-value-1", "groq-secret-value-2")


def no_secrets(*texts):
    return all(secret not in str(text) for text in texts for secret in SECRETS)


# --- providers ----------------------------------------------------------------------------------------------------


def test_providers_list_the_key_variable_and_whether_it_is_set_but_never_the_key(staff_client, registry, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")

    response = staff_client.get("/api/console/providers")
    by_key = {p["key"]: p for p in response.json()["results"]}

    assert by_key["gemini"] == {
        "key": "gemini", "kind": "google_genai", "api_key_env": "GEMINI_API_KEY", "api_key_set": True,
        "base_url": "", "rpm_limit": 10, "enabled": True, "models_count": 2, "spend_7d": "0.000000",
    }  # fmt: skip
    assert (by_key["groq"]["api_key_set"], by_key["groq"]["models_count"]) == (False, 1)
    assert no_secrets(response.content)


def test_a_provider_that_needs_no_key_counts_as_set(staff_client, db):
    Provider.objects.create(key="local", kind="ollama", base_url="http://localhost:11434")

    [provider] = staff_client.get("/api/console/providers").json()["results"]

    assert (provider["api_key_env"], provider["api_key_set"]) == ("", True)


def test_seven_day_spend_is_per_provider_and_ignores_older_calls(staff_client, registry, make_call):
    make_call(provider_key="gemini", cost="0.010000", ago=1 * H)
    make_call(provider_key="gemini", cost="0.020000", ago=6 * D)
    make_call(provider_key="gemini", cost="5.000000", ago=8 * D)  # a week ago and more
    make_call(provider_key="groq", cost="0.003000", ago=2 * H, model_name="openai/gpt-oss-120b")

    spend = {p["key"]: p["spend_7d"] for p in staff_client.get("/api/console/providers").json()["results"]}

    assert spend == {"gemini": "0.030000", "groq": "0.003000"}


def test_providers_are_listed_by_key(staff_client, registry):
    keys = [p["key"] for p in staff_client.get("/api/console/providers").json()["results"]]

    assert keys == ["gemini", "groq"]


def test_a_provider_can_be_throttled_repointed_and_switched_off(staff_client, staff_user, registry, db):
    local = Provider.objects.create(key="local", kind="ollama", base_url="http://localhost:11434")

    response = staff_client.patch(
        "/api/console/providers/local",
        {"rpm_limit": 30, "base_url": "http://192.168.1.20:11434", "enabled": False},
        format="json",
    )

    assert response.status_code == 200
    local.refresh_from_db()
    assert (local.rpm_limit, local.base_url, local.is_enabled) == (30, "http://192.168.1.20:11434", False)
    assert response.json()["rpm_limit"] == 30 and response.json()["enabled"] is False
    [entry] = AuditEntry.objects.all()
    assert (entry.actor_id, entry.action, entry.target_type, entry.target_id) == (staff_user.id, "provider.update",
                                                                                   "provider", "local")  # fmt: skip
    assert entry.before["rpm_limit"] is None and entry.after["rpm_limit"] == 30
    assert entry.before["enabled"] is True and entry.after["enabled"] is False


def test_a_rate_limit_can_be_cleared_with_null(staff_client, registry):
    response = staff_client.patch("/api/console/providers/gemini", {"rpm_limit": None}, format="json")

    assert response.status_code == 200 and Provider.objects.get(key="gemini").rpm_limit is None


@pytest.mark.parametrize(
    ("provider", "body", "field"),
    [
        ("gemini", {"base_url": "http://elsewhere.test"}, "base_url"),  # only Ollama and compatible vendors take one
        ("gemini", {"rpm_limit": 0}, "rpm_limit"),
        ("gemini", {"rpm_limit": "fast"}, "rpm_limit"),
        ("gemini", {"base_url": "not a url"}, "base_url"),
        ("local", {"base_url": ""}, "base_url"),  # Ollama needs one
    ],
)
def test_a_provider_change_the_admin_would_refuse_is_refused_and_changes_nothing(
    staff_client, registry, provider, body, field
):
    Provider.objects.create(key="local", kind="ollama", base_url="http://localhost:11434")
    before = list(Provider.objects.values())

    response = staff_client.patch(f"/api/console/providers/{provider}", body, format="json")

    assert response.status_code == 400 and field in response.json()["fields"]
    assert list(Provider.objects.values()) == before and not AuditEntry.objects.exists()


@pytest.mark.parametrize("field", ["key", "kind", "api_key_env", "api_key", "id"])
def test_nothing_about_a_providers_key_or_identity_can_be_set_here(staff_client, registry, field):
    response = staff_client.patch("/api/console/providers/gemini", {field: "OTHER_KEY"}, format="json")

    assert response.status_code == 400 and field in response.json()["fields"]
    assert Provider.objects.get(key="gemini").api_key_env == "GEMINI_API_KEY"


def test_an_unknown_provider_is_a_404(staff_client, registry):
    assert staff_client.patch("/api/console/providers/nobody", {"enabled": False}, format="json").status_code == 404


# --- models --------------------------------------------------------------------------------------------------------


def test_a_model_lists_its_capabilities_limits_prices_steps_and_last_test(staff_client, registry):
    registry.bind("lesson.plan", "flash")
    registry.bind("page.generate", "flash")
    LLMModel.objects.filter(pk=registry.models["flash"].pk).update(
        input_cost_per_mtok="0.3000", output_cost_per_mtok="2.5000", rpm_limit=10, label="Gemini 3.5 Flash"
    )

    body = staff_client.get("/api/console/models").json()
    flash = next(m for m in body["results"] if m["name"] == "gemini-3.5-flash")

    assert flash == {
        "id": registry.models["flash"].id, "provider": "gemini", "name": "gemini-3.5-flash",
        "label": "Gemini 3.5 Flash", "enabled": True, "api_key_set": True, "default_params": {"temperature": 0.5},
        "supports_structured_output": True, "structured_output_method": "json_schema", "supports_tool_calling": True,
        "supports_parallel_tool_calls": False, "supports_vision": True, "supports_reasoning": False,
        "reasoning_control": "none", "reasoning_disables_sampling": False, "context_window": 1_000_000,
        "max_output_tokens": 65_536, "rpm_limit": 10, "input_cost_per_mtok": "0.3000",
        "output_cost_per_mtok": "2.5000", "bound_nodes": ["lesson.plan", "page.generate"], "last_probe": None,
    }  # fmt: skip
    assert {"next", "previous", "results"} <= set(body)


def test_the_models_query_count_does_not_grow_with_the_models(staff_client, registry, count_queries):
    def fetch():
        assert staff_client.get("/api/console/models").status_code == 200

    registry.bind("lesson.plan", "flash")
    few = count_queries(fetch)
    for index, node in enumerate(("page.generate", "test.generate", "learner.assess")):
        model = LLMModel.objects.create(provider=registry.providers["gemini"], name=f"extra-{index}",
                                        supports_structured_output=True, max_output_tokens=65_536,
                                        context_window=1_000_000)  # fmt: skip
        registry.models[f"x{index}"] = model
        registry.bind(node, f"x{index}")

    assert count_queries(fetch) == few


NEW_MODEL = {
    "provider": "groq", "name": "openai/gpt-oss-20b", "label": "GPT-OSS 20B", "default_params": {"temperature": 0.4},
    "supports_structured_output": True, "supports_tool_calling": True, "supports_reasoning": True,
    "reasoning_control": "effort", "context_window": 131_072, "max_output_tokens": 65_536, "rpm_limit": 30,
    "input_cost_per_mtok": "0.0750", "output_cost_per_mtok": "0.3000",
}  # fmt: skip


def test_a_model_can_be_added(staff_client, staff_user, registry):
    response = staff_client.post("/api/console/models", NEW_MODEL, format="json")

    assert response.status_code == 201
    model = LLMModel.objects.get(name="openai/gpt-oss-20b")
    assert (model.provider.key, model.rpm_limit, model.is_enabled, str(model.input_cost_per_mtok)) == (
        "groq", 30, True, "0.0750")  # fmt: skip
    assert response.json()["id"] == model.id and response.json()["provider"] == "groq"
    [entry] = AuditEntry.objects.all()
    assert (entry.action, entry.target_type, entry.target_id, entry.before) == ("model.create", "model",
                                                                                 str(model.id), None)  # fmt: skip
    assert entry.after["name"] == "openai/gpt-oss-20b" and entry.after["input_cost_per_mtok"] == "0.0750"


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"name": "openai/gpt-oss-120b"}, "__all__"),  # already there on groq
        ({"default_params": {"top_k": 3}}, "default_params"),  # groq takes no top_k
        ({"default_params": ["temperature"]}, "default_params"),
        ({"supports_reasoning": True, "reasoning_control": "none"}, "reasoning_control"),
        ({"provider": "nobody"}, "provider"),
        ({"name": ""}, "name"),
        ({"context_window": -1}, "context_window"),
        ({"structured_output_method": "magic"}, "structured_output_method"),
        ({"input_cost_per_mtok": "cheap"}, "input_cost_per_mtok"),
    ],
)
def test_a_model_the_admin_would_refuse_is_refused(staff_client, registry, change, field):
    before = LLMModel.objects.count()

    response = staff_client.post("/api/console/models", {**NEW_MODEL, **change}, format="json")

    body = response.json()
    assert response.status_code == 400
    assert (field in body.get("fields", {})) or (field == "__all__" and "already exists" in body["detail"])
    assert LLMModel.objects.count() == before and not AuditEntry.objects.exists()


def test_a_model_needs_a_provider_and_a_name(staff_client, registry):
    response = staff_client.post("/api/console/models", {"label": "x"}, format="json")

    assert {"provider", "name"} <= set(response.json()["fields"])


def test_a_model_can_be_changed_but_not_moved_to_another_provider(staff_client, staff_user, registry):
    model = registry.models["lite"]

    response = staff_client.patch(
        f"/api/console/models/{model.id}",
        {
            "label": "Lite",
            "enabled": False,
            "rpm_limit": 15,
            "input_cost_per_mtok": "0.1000",
            "default_params": {"temperature": 0.2},
        },  # fmt: skip
        format="json",
    )

    assert response.status_code == 200
    model.refresh_from_db()
    assert (model.label, model.is_enabled, model.rpm_limit) == ("Lite", False, 15)
    assert model.default_params == {"temperature": 0.2}
    [entry] = AuditEntry.objects.all()
    assert (entry.action, entry.before["enabled"], entry.after["enabled"]) == ("model.update", True, False)
    assert staff_client.patch(f"/api/console/models/{model.id}", {"provider": "groq"}, format="json").status_code == 400


def test_a_model_can_be_renamed(staff_client, registry):
    model = registry.models["lite"]

    staff_client.patch(f"/api/console/models/{model.id}", {"name": "gemini-3.5-flash-lite-002"}, format="json")

    assert LLMModel.objects.get(pk=model.pk).name == "gemini-3.5-flash-lite-002"


def test_parameter_values_the_vendor_would_reject_are_refused_on_a_change_too(staff_client, registry):
    model = registry.models["flash"]

    response = staff_client.patch(f"/api/console/models/{model.id}",
                                  {"default_params": {"temperature": "hot"}}, format="json")  # fmt: skip

    assert response.status_code == 400 and "default_params" in response.json()["fields"]
    assert LLMModel.objects.get(pk=model.pk).default_params == {"temperature": 0.5}


def test_the_model_endpoints_404_for_an_unknown_model(staff_client, registry):
    assert staff_client.patch("/api/console/models/99999", {"label": "x"}, format="json").status_code == 404
    assert staff_client.delete("/api/console/models/99999").status_code == 404
    assert staff_client.post("/api/console/models/99999/probe").status_code == 404


def test_a_model_no_step_uses_can_be_deleted(staff_client, staff_user, registry):
    model = registry.models["lite"]

    response = staff_client.delete(f"/api/console/models/{model.id}")

    assert response.status_code == 204 and not LLMModel.objects.filter(pk=model.pk).exists()
    [entry] = AuditEntry.objects.all()
    assert (entry.action, entry.target_id, entry.after) == ("model.delete", str(model.id), None)
    assert entry.before["name"] == "gemini-3.5-flash-lite"


def test_a_model_a_step_uses_is_not_deleted_and_the_steps_are_named(staff_client, registry):
    registry.bind("lesson.plan", "flash")
    registry.bind("page.generate", "flash", priority=1)
    model = registry.models["flash"]

    response = staff_client.delete(f"/api/console/models/{model.id}")

    body = response.json()
    assert (response.status_code, body["code"]) == (409, "model_in_use")
    assert body["nodes"] == ["lesson.plan", "page.generate"]
    assert "lesson.plan" in body["detail"] and "page.generate" in body["detail"]
    assert LLMModel.objects.filter(pk=model.pk).exists() and not AuditEntry.objects.exists()


# --- testing a model ----------------------------------------------------------------------------------------------


class Chat:
    """Answers every probe like a capable model; `fail` makes the plain call raise that error."""

    def __init__(self, fail=None, on_call=None):
        self.fail, self.on_call = fail, on_call

    def invoke(self, messages):
        if self.on_call:
            self.on_call()
        if self.fail:
            raise self.fail
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
def chat(monkeypatch):
    """Install a chat factory (as the existing probe tests do) and return the list of timeouts it was asked for."""
    timeouts = []

    def install(**kwargs):
        def factory(model, timeout_s):
            timeouts.append(timeout_s)
            return Chat(**kwargs)

        monkeypatch.setattr("llm_registry.providers.CHAT_MODEL_FACTORY", factory)
        return timeouts

    return install


def test_testing_a_working_model_says_ok_and_stores_the_result(staff_client, staff_user, registry, chat, now):
    chat()
    model = registry.models["flash"]

    response = staff_client.post(f"/api/console/models/{model.id}/probe")

    body = response.json()
    assert response.status_code == 200 and body["ok"] is True and body["error"] is None
    assert isinstance(body["latency_s"], float) and body["latency_s"] >= 0
    assert [c["capability"] for c in body["checks"]] == ["text", "structured_output", "tool_calling", "vision"]
    assert all(c["ok"] for c in body["checks"])
    model.refresh_from_db()
    assert (model.last_probe_ok, model.last_probe_at, model.last_probe_error) == (True, now, "")
    assert model.last_probe_latency_s == body["latency_s"]
    [entry] = AuditEntry.objects.all()
    assert (entry.action, entry.target_type, entry.target_id) == ("model.probe", "model", str(model.id))
    assert entry.before is None or entry.before["ok"] is None
    assert entry.after["ok"] is True


def test_the_last_test_shows_in_the_model_list(staff_client, registry, chat, now):
    chat()
    staff_client.post(f"/api/console/models/{registry.models['oss'].id}/probe")

    [oss] = [m for m in staff_client.get("/api/console/models").json()["results"] if m["provider"] == "groq"]

    assert oss["last_probe"] == {"at": "2026-03-15T12:00:00Z", "ok": True, "latency_s": oss["last_probe"]["latency_s"],
                                 "error": ""}  # fmt: skip


def test_only_the_capabilities_a_model_claims_are_tested(staff_client, registry, chat):
    chat()

    body = staff_client.post(f"/api/console/models/{registry.models['oss'].id}/probe").json()  # no vision

    assert [c["capability"] for c in body["checks"]] == ["text", "structured_output", "tool_calling"]


def test_a_model_that_fails_is_reported_with_the_reason_and_without_the_key(staff_client, registry, chat):
    chat(fail=RuntimeError("401 invalid key gsk_abcdefghijklmnopqrstuvwxyz"))
    model = registry.models["oss"]

    response = staff_client.post(f"/api/console/models/{model.id}/probe")

    body = response.json()
    assert response.status_code == 200 and body["ok"] is False
    assert body["error"].startswith("text: RuntimeError") and "gsk_" not in body["error"]
    model.refresh_from_db()
    assert model.last_probe_ok is False and model.last_probe_error == body["error"]
    assert AuditEntry.objects.get().after["ok"] is False


def test_a_provider_without_its_key_fails_the_test_without_a_call(staff_client, registry, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")  # the real chat factory refuses to build the client

    body = staff_client.post(f"/api/console/models/{registry.models['oss'].id}/probe").json()

    assert body["ok"] is False and "GROQ_API_KEY" in body["error"] and body["latency_s"] is None
    assert [c["capability"] for c in body["checks"]] == ["setup"]


def test_each_test_call_is_given_no_more_time_than_is_left(staff_client, registry, chat):
    timeouts = chat()

    staff_client.post(f"/api/console/models/{registry.models['flash'].id}/probe")

    assert timeouts and all(1 <= t <= 20 for t in timeouts)


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def __call__(self):
        return self.seconds


def test_a_test_that_runs_out_of_time_stops_and_says_so(registry):
    clock = Clock()
    model = registry.models["flash"]
    service = ModelProbeService(
        chat_factory=lambda m, timeout: Chat(on_call=lambda: setattr(clock, "seconds", clock.seconds + 25)),
        clock=clock,
        timeout_s=20,
    )

    outcome = service.probe(model)

    assert outcome.ok is False and "20 s" in outcome.error and "Timed out" in outcome.error
    assert [c.capability for c in outcome.checks] == ["text", "structured_output"]  # the text call used up the time
    assert outcome.checks[0].ok and not outcome.checks[1].ok


def test_a_test_that_finishes_in_time_runs_every_check(registry):
    clock = Clock()
    service = ModelProbeService(chat_factory=lambda m, timeout: Chat(), clock=clock, timeout_s=20)

    outcome = service.probe(registry.models["flash"])

    assert outcome.ok and len(outcome.checks) == 4 and outcome.error is None


def test_testing_is_not_open_to_a_learner(learner_client, registry):
    assert learner_client.post(f"/api/console/models/{registry.models['flash'].id}/probe").status_code == 404


def test_no_secret_reaches_the_responses_or_the_log(staff_client, registry, chat):
    chat(fail=RuntimeError("bad key groq-secret-value-2 for gemini-secret-value-1"))
    responses = [
        staff_client.get("/api/console/providers"),
        staff_client.get("/api/console/models"),
        staff_client.patch("/api/console/providers/gemini", {"rpm_limit": 5}, format="json"),
        staff_client.post(f"/api/console/models/{registry.models['oss'].id}/probe"),
        staff_client.get("/api/console/models"),
    ]

    logged = [(e.before, e.after) for e in AuditEntry.objects.all()]

    assert no_secrets(*(r.content for r in responses), logged, list(LLMModel.objects.values()))

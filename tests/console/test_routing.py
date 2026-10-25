"""Unit under test: `console.services.routing` (`NodeRoutingReader`, `NodeRoutingValidator`, `NodeRoutingWriter`,
`ProfilePreview`), behind `GET /api/console/nodes`, `PUT /api/console/nodes/{key}`, `GET /api/console/profiles` and
`POST /api/console/profiles/{name}/preview`.

Why: routing decides which model writes each part of every lesson. A save that half-applies leaves a step with no
model, a chain with a model that cannot serve the step fails lessons at the worst moment, and a profile applied
blind could switch the whole product to models that have no key. Everything is checked before anything is written.

Use cases:
- the nodes come grouped by phase in lesson order, each with its description, whether it is required, what it
  needs, its settings and its models in priority order, with the problems the current chain has
- a step is saved in one go: its settings and its whole chain replace the old ones, priorities follow the order sent
- required steps cannot be switched off; optional ones can, with no models; an enabled step needs an enabled model
- every model in the chain must exist, be switched on, have its provider's key set, and be able to serve the step
  (capabilities, output size, context, parameters the provider accepts); a model appears once
- settings are range-checked (attempts, timeout, effort, tool steps for tool steps only)
- a refused save changes nothing and logs nothing; an accepted one is one audit entry with the step before and after
- a save that fails half way rolls back, chain included
- profiles list their name, label and description; previewing one shows, for each step, what would change, with the
  models resolved from the registry and what is wrong with them, and saves nothing
- none of it is open to a learner
"""

import pytest

from console.models import AuditEntry
from console.services.routing import (
    NodeRoutingValidator,
    NodeRoutingWriter,
    ProposedBinding,
    ProposedNode,
)
from llm_registry.models import LLMModel, NodeConfig, NodeModelBinding
from llm_registry.node_specs import NODE_SPECS
from llm_registry.seed import DefaultRegistry
from llm_registry.serialization import RegistrySerializer

pytestmark = pytest.mark.django_db


def put(client, key, **changes):
    body = {"enabled": True, "reasoning_effort": "medium", "max_attempts": 2, "timeout_s": 60, "bindings": []}
    return client.put(f"/api/console/nodes/{key}", {**body, **changes}, format="json")


def chain(registry, *names, **extra):
    return [{"model": registry.models[name].id, "max_retries": 2, **extra} for name in names]


def stored(key):
    node = NodeConfig.objects.get(node_key=key)
    return (
        node.is_enabled, node.reasoning_effort, node.max_attempts, node.timeout_s,
        [(b.model.name, b.priority, b.max_retries) for b in node.bindings.order_by("priority")],
    )  # fmt: skip


def flat(body):
    return {node["key"]: node for group in body["phases"] for node in group["nodes"]}


# --- reading ------------------------------------------------------------------------------------------------------


def test_nodes_are_grouped_by_phase_in_lesson_order_with_what_each_needs(staff_client, registry):
    body = staff_client.get("/api/console/nodes").json()

    assert [group["phase"] for group in body["phases"]] == ["diagnose", "author", "build", "post", "onboarding"]
    nodes = flat(body)
    assert set(nodes) == set(NODE_SPECS)
    assert [n["key"] for n in body["phases"][0]["nodes"]][:2] == ["diagnostic.generate", "diagnostic.review"]
    verify = nodes["media.verify"]
    assert verify["description"] == NODE_SPECS["media.verify"].description
    assert (verify["optional"], verify["output"], verify["requires"]) == (
        True,
        "structured",
        ["structured_output", "vision"],
    )
    assert (verify["min_output_tokens"], verify["min_context"]) == (1024, 32_000)
    assert nodes["lesson.plan"]["optional"] is False and nodes["media.search"]["max_tool_steps"] == 6


def test_a_nodes_models_come_in_priority_order_with_their_settings(staff_client, registry):
    registry.bind("lesson.plan", "lite", priority=1, max_retries=1, params_override={"temperature": 0.1},
                  reasoning_effort="high")  # fmt: skip
    registry.bind("lesson.plan", "flash", priority=0)
    NodeConfig.objects.filter(node_key="lesson.plan").update(reasoning_effort="high", timeout_s=90)

    plan = flat(staff_client.get("/api/console/nodes").json())["lesson.plan"]

    assert (plan["enabled"], plan["reasoning_effort"], plan["max_attempts"], plan["timeout_s"]) == (True, "high", 2, 90)
    assert plan["bindings"] == [
        {"model": registry.models["flash"].id, "model_label": "gemini/gemini-3.5-flash", "enabled": True,
         "max_retries": 2, "overrides": {"params": {}, "reasoning_effort": ""}, "problems": []},
        {"model": registry.models["lite"].id, "model_label": "gemini/gemini-3.5-flash-lite", "enabled": True,
         "max_retries": 1, "overrides": {"params": {"temperature": 0.1}, "reasoning_effort": "high"}, "problems": []},
    ]  # fmt: skip


def test_a_chain_that_cannot_serve_its_step_shows_why(staff_client, registry):
    registry.bind("media.verify", "oss")  # no vision

    [binding] = flat(staff_client.get("/api/console/nodes").json())["media.verify"]["bindings"]

    assert len(binding["problems"]) == 1 and "vision" in binding["problems"][0]


def test_the_nodes_query_count_does_not_grow_with_the_bindings(staff_client, registry, count_queries):
    def fetch():
        assert staff_client.get("/api/console/nodes").status_code == 200

    registry.bind("lesson.plan", "flash")
    few = count_queries(fetch)
    for node in ("page.generate", "test.generate", "learner.assess", "diagnostic.generate"):
        registry.bind(node, "flash")
        registry.bind(node, "lite", priority=1)
        registry.bind(node, "oss", priority=2)

    assert count_queries(fetch) == few


# --- saving a step ------------------------------------------------------------------------------------------------


def test_a_step_is_saved_with_its_settings_and_its_whole_chain(staff_client, staff_user, registry):
    registry.bind("lesson.plan", "flash", priority=0)
    registry.bind("lesson.plan", "oss", priority=1)

    response = put(staff_client, "lesson.plan", reasoning_effort="high", max_attempts=3, timeout_s=120,
                   params_override={"temperature": 0.2}, bindings=chain(registry, "lite", "flash"))  # fmt: skip

    assert response.status_code == 200
    assert stored("lesson.plan") == (
        True,
        "high",
        3,
        120,
        [("gemini-3.5-flash-lite", 0, 2), ("gemini-3.5-flash", 1, 2)],
    )
    assert NodeConfig.objects.get(node_key="lesson.plan").params_override == {"temperature": 0.2}
    assert [b["model_label"] for b in response.json()["bindings"]] == ["gemini/gemini-3.5-flash-lite",
                                                                       "gemini/gemini-3.5-flash"]  # fmt: skip
    assert response.json() == flat(staff_client.get("/api/console/nodes").json())["lesson.plan"]
    assert NodeModelBinding.objects.filter(node__node_key="lesson.plan").count() == 2


def test_the_overrides_of_a_binding_are_kept(staff_client, registry):
    bindings = chain(registry, "flash", overrides={"params": {"temperature": 0.9}, "reasoning_effort": "low"},
                     max_retries=0, enabled=True)  # fmt: skip

    put(staff_client, "lesson.plan", bindings=bindings)

    binding = NodeModelBinding.objects.get(node__node_key="lesson.plan")
    assert (binding.params_override, binding.reasoning_effort, binding.max_retries) == ({"temperature": 0.9}, "low", 0)


def test_a_binding_can_be_parked_switched_off_in_the_chain(staff_client, registry):
    bindings = chain(registry, "flash") + chain(registry, "lite", enabled=False)

    assert put(staff_client, "lesson.plan", bindings=bindings).status_code == 200

    assert [b.is_enabled for b in NodeModelBinding.objects.order_by("priority")] == [True, False]


def test_saving_writes_one_audit_entry_with_the_step_before_and_after(staff_client, staff_user, registry):
    registry.bind("lesson.plan", "flash")

    put(staff_client, "lesson.plan", reasoning_effort="low", bindings=chain(registry, "lite"))

    [entry] = AuditEntry.objects.all()
    assert (entry.actor_id, entry.action, entry.target_type, entry.target_id) == (staff_user.id, "node.update", "node",
                                                                                   "lesson.plan")  # fmt: skip
    assert entry.before["reasoning_effort"] == "high"  # the step's own default
    assert entry.after["reasoning_effort"] == "low"
    assert [b["model_label"] for b in entry.before["bindings"]] == ["gemini/gemini-3.5-flash"]
    assert [b["model_label"] for b in entry.after["bindings"]] == ["gemini/gemini-3.5-flash-lite"]


def test_a_required_step_cannot_be_switched_off(staff_client, registry):
    registry.bind("learner.assess", "flash")

    response = put(staff_client, "learner.assess", enabled=False, bindings=chain(registry, "flash"))

    assert response.status_code == 400 and "enabled" in response.json()["fields"]
    assert stored("learner.assess")[0] is True


def test_an_optional_step_can_be_switched_off_and_needs_no_models(staff_client, registry):
    registry.bind("diagnostic.review", "flash")

    response = put(staff_client, "diagnostic.review", enabled=False, bindings=[])

    assert response.status_code == 200
    assert stored("diagnostic.review") == (False, "medium", 2, 60, [])


@pytest.mark.parametrize("bindings", ["none", "only_parked"])
def test_an_enabled_step_needs_an_enabled_model(staff_client, registry, bindings):
    registry.bind("lesson.plan", "flash")
    body = [] if bindings == "none" else chain(registry, "lite", enabled=False)

    response = put(staff_client, "lesson.plan", bindings=body)

    assert response.status_code == 400 and "bindings" in response.json()["fields"]
    assert stored("lesson.plan")[4] == [("gemini-3.5-flash", 0, 2)]


def refused(client, registry, expected, **changes):
    """Save with `changes`, expect a 400 whose field messages mention `expected`, and nothing changed or logged."""
    registry.bind("lesson.plan", "flash")
    before = stored("lesson.plan")

    response = put(client, "lesson.plan", **changes)

    assert response.status_code == 400, response.json()
    fields = response.json()["fields"]
    assert any(expected in message for messages in fields.values() for message in messages), fields
    assert stored("lesson.plan") == before and not AuditEntry.objects.exists()
    return fields


def test_a_model_that_does_not_exist_is_refused(staff_client, registry):
    refused(
        staff_client, registry, "model 999999 is not in your registry", bindings=[{"model": 999_999, "max_retries": 2}]
    )


def test_a_provider_whose_key_is_not_set_is_refused_naming_the_variable(staff_client, registry, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")

    refused(staff_client, registry, "GROQ_API_KEY", bindings=chain(registry, "flash", "oss"))


def test_a_parked_binding_does_not_need_its_providers_key(staff_client, registry, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")

    assert (
        put(
            staff_client, "lesson.plan", bindings=chain(registry, "flash") + chain(registry, "oss", enabled=False)
        ).status_code
        == 200
    )


def test_a_switched_off_model_or_provider_is_refused(staff_client, registry):
    LLMModel.objects.filter(pk=registry.models["lite"].pk).update(is_enabled=False)

    refused(staff_client, registry, "switched off", bindings=chain(registry, "flash", "lite"))


def test_a_model_missing_a_capability_the_step_needs_is_refused(staff_client, registry):
    registry.bind("media.verify", "flash")
    before = stored("media.verify")

    response = put(staff_client, "media.verify", bindings=chain(registry, "oss"))  # the picture check reads pictures

    assert response.status_code == 400
    assert "vision" in " ".join(response.json()["fields"]["bindings"])
    assert stored("media.verify") == before and not AuditEntry.objects.exists()


def test_a_model_that_cannot_write_enough_or_read_enough_is_refused(staff_client, registry):
    small = LLMModel.objects.create(provider=registry.providers["gemini"], name="tiny", supports_structured_output=True,
                                    max_output_tokens=1000, context_window=4000)  # fmt: skip
    registry.models["tiny"] = small

    fields = refused(staff_client, registry, "outputs at most 1000 tokens", bindings=chain(registry, "tiny"))

    assert "context" in " ".join(fields["bindings"])


def test_a_parameter_the_provider_rejects_is_refused(staff_client, registry):
    bindings = chain(registry, "oss", overrides={"params": {"top_k": 3}})  # groq takes no top_k

    refused(staff_client, registry, "top_k", bindings=bindings)


def test_the_same_model_twice_in_a_chain_is_refused(staff_client, registry):
    refused(staff_client, registry, "more than once", bindings=chain(registry, "flash", "flash"))


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"max_attempts": 11}, "max_attempts"),
        ({"timeout_s": 0}, "timeout_s"),
        ({"timeout_s": 601}, "timeout_s"),
        ({"reasoning_effort": "extreme"}, "reasoning_effort"),
        ({"max_tool_steps": 3}, "max_tool_steps"),  # lesson.plan is not a tool-calling step
        ({"params_override": [1]}, "params_override"),
    ],
)
def test_settings_out_of_range_are_refused(staff_client, registry, change, field):
    registry.bind("lesson.plan", "flash")
    before = stored("lesson.plan")

    response = put(staff_client, "lesson.plan", bindings=chain(registry, "flash"), **change)

    assert response.status_code == 400 and field in response.json()["fields"]
    assert stored("lesson.plan") == before


def test_a_tool_step_needs_a_tool_step_limit(staff_client, registry):
    response = put(staff_client, "media.search", bindings=chain(registry, "flash"))

    assert response.status_code == 400 and "max_tool_steps" in response.json()["fields"]
    assert put(staff_client, "media.search", bindings=chain(registry, "flash"), max_tool_steps=4).status_code == 200


@pytest.mark.parametrize("missing", ["enabled", "reasoning_effort", "max_attempts", "timeout_s", "bindings"])
def test_a_save_replaces_everything_so_every_setting_is_required(staff_client, registry, missing):
    body = {"enabled": True, "reasoning_effort": "low", "max_attempts": 2, "timeout_s": 60,
            "bindings": chain(registry, "flash")}  # fmt: skip
    body.pop(missing)

    response = staff_client.put("/api/console/nodes/lesson.plan", body, format="json")

    assert response.status_code == 400 and missing in response.json()["fields"]


def test_an_unknown_step_is_a_404(staff_client, registry):
    assert put(staff_client, "no.such.step").status_code == 404


def proposed_for(registry, *names, **changes):
    values = dict(enabled=True, reasoning_effort="high", max_attempts=2, max_tool_steps=None, timeout_s=60,
                  params_override={})  # fmt: skip
    bindings = tuple(ProposedBinding(model=registry.models[n], label=str(registry.models[n])) for n in names)
    return ProposedNode(**{**values, **changes, "bindings": bindings})


def test_a_save_that_fails_half_way_rolls_back_the_chain_too(registry):
    class ExplodingTrail:
        def record(self, *args, **kwargs):
            raise RuntimeError("the audit log is down")

    registry.bind("lesson.plan", "flash")
    node = NodeConfig.objects.get(node_key="lesson.plan")
    before = stored("lesson.plan")

    with pytest.raises(RuntimeError, match="audit log"):
        NodeRoutingWriter(ExplodingTrail()).replace(node, proposed_for(registry, "lite", reasoning_effort="low"))

    assert stored("lesson.plan") == before


def test_the_validator_collects_every_problem_at_once(registry, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    node = NodeConfig.objects.get(node_key="media.verify")

    problems = NodeRoutingValidator().problems(node, proposed_for(registry, "oss", "oss"))

    text = " ".join(problems["bindings"])
    assert "GROQ_API_KEY" in text and "vision" in text and "more than once" in text


def test_the_validator_has_nothing_to_say_about_a_good_chain(registry):
    node = NodeConfig.objects.get(node_key="media.verify")

    assert NodeRoutingValidator().problems(node, proposed_for(registry, "flash", "lite")) == {}


def test_a_learner_cannot_read_or_save_routing(learner_client, registry):
    assert learner_client.get("/api/console/nodes").status_code == 404
    assert put(learner_client, "lesson.plan").status_code == 404
    assert learner_client.get("/api/console/profiles").status_code == 404
    assert learner_client.post("/api/console/profiles/cheap/preview").status_code == 404


# --- profiles -----------------------------------------------------------------------------------------------------


def test_the_profiles_on_offer_are_listed_with_what_they_are_for(staff_client, db):
    body = staff_client.get("/api/console/profiles").json()

    assert [p["name"] for p in body] == ["default", "cheap", "balanced", "quality"]
    assert body[1] == {"name": "cheap", "label": "Cheap", "nodes": len(NODE_SPECS),
                       "description": body[1]["description"]}  # fmt: skip
    assert "cheapest" in body[1]["description"]


def export():
    return RegistrySerializer().export()


@pytest.fixture
def full_registry(db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret-value-1")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret-value-2")
    RegistrySerializer().load(DefaultRegistry().build())


def test_previewing_a_profile_shows_each_step_as_it_is_and_as_it_would_be_and_saves_nothing(
    staff_client, full_registry
):
    before = export()

    response = staff_client.post("/api/console/profiles/cheap/preview")

    assert response.status_code == 200
    body = response.json()
    nodes = {n["key"]: n for n in body["nodes"]}
    assert body["profile"] == "cheap" and set(nodes) == set(NODE_SPECS)
    plan = nodes["lesson.plan"]
    assert plan["changed"] is True
    assert [b["model_label"] for b in plan["current"]["bindings"]] == [
        "gemini/gemini-3.5-flash", "groq/openai/gpt-oss-120b", "gemini/gemini-3.5-flash-lite"]  # fmt: skip
    assert [b["model_label"] for b in plan["proposed"]["bindings"]] == [
        "gemini/gemini-3.5-flash-lite", "gemini/gemini-3.1-flash-lite"]  # fmt: skip
    assert plan["proposed"]["reasoning_effort"] == "low" and plan["current"]["reasoning_effort"] == "high"
    assert plan["problems"] == [] and all(b["model"] for b in plan["proposed"]["bindings"])
    assert body["summary"]["total"] == len(NODE_SPECS) and body["summary"]["changed"] >= 10
    assert export() == before and not AuditEntry.objects.exists()


def test_a_proposed_step_can_be_saved_as_it_is(staff_client, full_registry):
    def page_generate():
        nodes = staff_client.post("/api/console/profiles/quality/preview").json()["nodes"]
        return next(n for n in nodes if n["key"] == "page.generate")

    before = page_generate()
    assert before["changed"] is True and before["current"]["reasoning_effort"] == "medium"
    proposed = before["proposed"]
    body = {key: proposed[key] for key in ("enabled", "reasoning_effort", "max_attempts", "max_tool_steps", "timeout_s",
                                           "params_override")}  # fmt: skip
    body["bindings"] = [
        {k: b[k] for k in ("model", "enabled", "max_retries", "overrides")} for b in proposed["bindings"]
    ]

    assert staff_client.put("/api/console/nodes/page.generate", body, format="json").status_code == 200

    assert flat(staff_client.get("/api/console/nodes").json())["page.generate"]["reasoning_effort"] == "high"
    assert page_generate()["changed"] is False


def test_previewing_the_profile_that_is_already_loaded_changes_nothing(staff_client, full_registry):
    body = staff_client.post("/api/console/profiles/default/preview").json()

    assert body["summary"] == {"total": len(NODE_SPECS), "changed": 0, "blocked": 0}
    assert not any(n["changed"] for n in body["nodes"])


def test_a_profile_asking_for_models_the_registry_lacks_says_which(staff_client, registry):
    body = staff_client.post("/api/console/profiles/default/preview").json()  # the registry has no gpt-oss-20b

    review = next(n for n in body["nodes"] if n["key"] == "diagnostic.review")
    assert any("openai/gpt-oss-20b" in p and "not in your registry" in p for p in review["problems"])
    missing = [b for n in body["nodes"] for b in n["proposed"]["bindings"] if b["model"] is None]
    assert missing and all(b["model_label"] for b in missing)
    assert body["summary"]["blocked"] > 0


def test_a_profile_whose_models_have_no_key_is_blocked_for_those_steps(staff_client, full_registry, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")

    body = staff_client.post("/api/console/profiles/cheap/preview").json()

    blocked = {n["key"] for n in body["nodes"] if n["problems"]}
    assert "diagnostic.generate" in blocked and "lesson.plan" not in blocked  # groq leads the first, not the second
    assert any("GROQ_API_KEY" in p for n in body["nodes"] for p in n["problems"])


def test_an_unknown_profile_is_a_404(staff_client, db):
    assert staff_client.post("/api/console/profiles/ultra/preview").status_code == 404

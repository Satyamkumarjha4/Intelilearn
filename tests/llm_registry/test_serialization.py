"""Unit under test: `llm_registry.serialization.RegistrySerializer` (registry <-> versioned JSON) and
`llm_registry.seed.DefaultRegistry`, plus the `seed_registry` and `export_registry` commands built on them.

Why: this is how a tuned registry moves between machines and how a fresh install gets working models. A half-applied
or unvalidated import would leave nodes bound to models that can't serve them.

Use cases:
- the default seed is valid, binds every required node, and switches the optional quality checks on with models that
  can do them (the quiz reviewer, and a vision model for the picture check)
- the default seed spreads the free tiers: Groq is the first choice on the light nodes (the big quiz at low effort),
  Gemini on the heavy ones, every chain has a fallback, and every model carries a requests-per-minute limit
- the "cheap" seed profile, for validating the flow without rate or billing limits, binds every node to only the
  cheapest models, at low reasoning effort, each with a second model behind it
- the onboarding topic suggester is seeded for speed: the small Groq model with a cheap Gemini behind it, low effort,
  one attempt, a 4 second timeout and no retries on a model (the next model is tried instead), in both profiles
- export then import round-trips to the same JSON, prices included (they are written as exact text, since a number like
  0.075 cannot be stored back into a four-decimal field), and a file from before that, with prices as numbers, loads
- an invalid import rolls back everything
- seed_registry leaves an existing registry alone unless forced, except that a node with no binding at all (a node a
  release added) is bound from the profile, using only models the install already has, never touching a binding that
  exists, and saying which nodes it bound and which it could not
- seed_registry loads an exported file
- seed_registry --profile cheap loads the cheap profile; an unknown profile is refused
"""

import json
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command

from llm_registry.models import LLMModel, NodeConfig, NodeModelBinding, Provider
from llm_registry.resolver import RegistryResolver
from llm_registry.seed import CheapRegistry, DefaultRegistry
from llm_registry.serialization import RegistrySerializer

pytestmark = pytest.mark.django_db


def test_default_seed_is_valid_and_covers_every_required_node():
    RegistrySerializer().load(DefaultRegistry().build())

    resolved = RegistryResolver().resolve()
    for node in NodeConfig.objects.all():
        if node.is_enabled:
            assert resolved[node.node_key].chain, f"{node.node_key} has no usable model"
    for key, chain in {
        "diagnostic.review": ["openai/gpt-oss-20b", "gemini-3.6-flash"],
        "media.verify": ["gemini-3.6-flash", "gemini-3.5-flash-lite"],
        "lesson.plan": ["gemini-3.6-flash", "openai/gpt-oss-120b", "gemini-3.5-flash-lite"],
    }.items():
        assert NodeConfig.objects.get(node_key=key).is_enabled
        assert [m.model_name for m in resolved[key].chain] == chain
    chain_names = [m.model_name for m in resolved["media.verify"].chain]
    assert all(m.supports_vision for m in LLMModel.objects.filter(name__in=chain_names))  # it reads the picture


@pytest.mark.parametrize("profile", [DefaultRegistry, CheapRegistry])
def test_topic_suggester_is_seeded_for_speed(profile):
    RegistrySerializer().load(profile().build())

    node = NodeConfig.objects.get(node_key="onboarding.suggest_topics")
    bindings = list(node.bindings.order_by("priority"))

    assert node.is_enabled
    assert (node.reasoning_effort, node.max_attempts, node.timeout_s) == ("low", 1, 4)
    assert [b.model.name for b in bindings][:2] == ["openai/gpt-oss-20b", "gemini-3.5-flash-lite"]
    assert {b.max_retries for b in bindings} == {0}


def test_default_seed_spreads_load_across_both_free_tiers():
    RegistrySerializer().load(DefaultRegistry().build())
    resolved = RegistryResolver().resolve()

    for key in ("diagnostic.generate", "diagnostic.review", "learner.assess", "interactive.plan", "media.search",
                "test.grade"):  # fmt: skip
        assert resolved[key].chain[0].provider_key == "groq", key
        assert resolved[key].chain[-1].provider_key == "gemini", key  # Gemini answers when Groq's quota is spent
    for key in ("study.generate", "page.generate", "test.generate", "interactive.generate", "alignment.judge",
                "page.compile", "code.repair", "runtime.repair"):  # fmt: skip
        assert resolved[key].chain[0].provider_key == "gemini", key  # big replies don't fit Groq's free token cap
    for key, node in resolved.items():
        assert len(node.chain) >= 2, f"{key} has no fallback"
    assert all(m.rpm_limit for m in LLMModel.objects.all())
    # gpt-oss drops required fields of the big quiz schema at medium effort (0 of 3 parsed) and keeps them at low
    assert NodeConfig.objects.get(node_key="diagnostic.generate").reasoning_effort == "low"


CHEAP_MODELS = {"gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "openai/gpt-oss-20b"}


def test_cheap_profile_binds_every_node_to_the_cheapest_models_at_low_effort():
    RegistrySerializer().load(CheapRegistry().build())
    resolved = RegistryResolver().resolve()

    for node in NodeConfig.objects.all():
        assert node.reasoning_effort == "low", node.node_key
        chain = resolved[node.node_key].chain
        assert len(chain) >= 2, f"{node.node_key} has no fallback"
        assert {m.model_name for m in chain} <= CHEAP_MODELS, node.node_key
    chain_names = [m.model_name for m in resolved["media.verify"].chain]
    assert all(m.supports_vision for m in LLMModel.objects.filter(name__in=chain_names))  # it reads the picture


def test_export_then_import_round_trips():
    RegistrySerializer().load(DefaultRegistry().build())
    exported = json.loads(json.dumps(RegistrySerializer().export()))
    NodeModelBinding.objects.all().delete()
    LLMModel.objects.all().delete()
    Provider.objects.all().delete()

    RegistrySerializer().load(exported)

    assert json.loads(json.dumps(RegistrySerializer().export())) == exported


def test_prices_typed_on_a_model_are_exported_as_exact_text():
    RegistrySerializer().load(DefaultRegistry().build())
    LLMModel.objects.filter(name="openai/gpt-oss-20b").update(
        input_cost_per_mtok=Decimal("0.075"), output_cost_per_mtok=Decimal("0.3")
    )

    models = {m["name"]: m for m in RegistrySerializer().export()["models"]}

    assert models["openai/gpt-oss-20b"]["input_cost_per_mtok"] == "0.075"
    assert models["openai/gpt-oss-20b"]["output_cost_per_mtok"] == "0.3"
    assert models["gemini-3.6-flash"]["input_cost_per_mtok"] is None  # the seed's prices are ModelPrice rows


def test_a_file_that_wrote_prices_as_numbers_still_loads():
    data = DefaultRegistry().build()
    for model in data["models"]:
        if model["name"] == "openai/gpt-oss-20b":
            model["input_cost_per_mtok"], model["output_cost_per_mtok"] = 0.075, 0.3

    RegistrySerializer().load(data)

    stored = LLMModel.objects.get(name="openai/gpt-oss-20b")
    assert (str(stored.input_cost_per_mtok), str(stored.output_cost_per_mtok)) == ("0.0750", "0.3000")


def test_invalid_import_rolls_back_everything():
    data = DefaultRegistry().build()
    data["nodes"][0]["bindings"].append({"provider": "groq", "model": "openai/gpt-oss-120b", "priority": 9,
                                         "params_override": {"top_k": 3}})  # fmt: skip

    with pytest.raises(ValidationError, match="top_k"):
        RegistrySerializer().load(data)

    assert not Provider.objects.exists()


def test_seed_command_is_idempotent(capsys):
    call_command("seed_registry")
    count = NodeModelBinding.objects.count()

    call_command("seed_registry")

    assert NodeModelBinding.objects.count() == count
    assert "leaving it alone" in capsys.readouterr().out


class TestUnboundNodes:
    """An install that already has a registry meets a release that adds a node: the node has no binding."""

    def unbind(self, node_key):
        NodeModelBinding.objects.filter(node__node_key=node_key).delete()

    def test_an_unbound_node_is_bound_from_the_profile_and_nothing_else_changes(self, capsys):
        call_command("seed_registry")
        self.unbind("prerequisites.plan")
        NodeModelBinding.objects.filter(node__node_key="lesson.plan", priority=0).update(priority=7)
        before = {
            (b.node.node_key, b.priority) for b in NodeModelBinding.objects.exclude(node__node_key="prerequisites.plan")
        }

        call_command("seed_registry")

        bound = list(NodeModelBinding.objects.filter(node__node_key="prerequisites.plan").order_by("priority"))
        assert [(b.model.provider.key, b.model.name) for b in bound] == [
            ("groq", "openai/gpt-oss-20b"), ("gemini", "gemini-3.6-flash")
        ]  # fmt: skip
        after = {
            (b.node.node_key, b.priority) for b in NodeModelBinding.objects.exclude(node__node_key="prerequisites.plan")
        }
        assert after == before  # a tuned binding is never overwritten
        out = capsys.readouterr().out
        assert "prerequisites.plan" in out and "Bound" in out

    def test_it_follows_the_chosen_profile(self):
        call_command("seed_registry", profile="cheap")
        self.unbind("prerequisites.plan")

        call_command("seed_registry", profile="cheap")

        names = set(
            NodeModelBinding.objects.filter(node__node_key="prerequisites.plan").values_list("model__name", flat=True)
        )
        assert names and names <= CHEAP_MODELS

    def test_only_models_the_install_has_are_used(self):
        call_command("seed_registry")
        self.unbind("prerequisites.plan")
        LLMModel.objects.filter(name="gemini-3.6-flash").exclude(
            pk__in=NodeModelBinding.objects.values("model")
        ).delete()
        NodeModelBinding.objects.filter(model__name="openai/gpt-oss-20b").delete()
        LLMModel.objects.filter(name="openai/gpt-oss-20b").delete()

        call_command("seed_registry")

        names = list(
            NodeModelBinding.objects.filter(node__node_key="prerequisites.plan").values_list("model__name", flat=True)
        )
        assert names == ["gemini-3.6-flash"]

    def test_a_node_the_install_has_no_model_for_is_reported_not_guessed(self, capsys):
        call_command("seed_registry")
        self.unbind("prerequisites.plan")
        NodeModelBinding.objects.filter(model__name__in=["openai/gpt-oss-20b", "gemini-3.6-flash"]).delete()
        LLMModel.objects.filter(name__in=["openai/gpt-oss-20b", "gemini-3.6-flash"]).delete()
        capsys.readouterr()

        call_command("seed_registry")

        assert not NodeModelBinding.objects.filter(node__node_key="prerequisites.plan").exists()
        assert "prerequisites.plan" in capsys.readouterr().out

    def test_a_registry_with_every_node_bound_is_left_alone(self, capsys):
        call_command("seed_registry")
        count = NodeModelBinding.objects.count()
        capsys.readouterr()

        call_command("seed_registry")

        assert NodeModelBinding.objects.count() == count and "leaving it alone" in capsys.readouterr().out

    def test_force_still_resets_everything(self):
        call_command("seed_registry")
        NodeModelBinding.objects.filter(node__node_key="lesson.plan", priority=0).update(priority=7)

        call_command("seed_registry", force=True)

        assert not NodeModelBinding.objects.filter(priority=7).exists()


def test_seed_command_loads_a_file(tmp_path):
    call_command("seed_registry")
    call_command("export_registry", output=tmp_path / "registry.json")
    NodeModelBinding.objects.all().delete()

    call_command("seed_registry", file=tmp_path / "registry.json")

    assert NodeModelBinding.objects.count() == sum(len(n["bindings"]) for n in DefaultRegistry().build()["nodes"])


def test_seed_command_loads_the_cheap_profile():
    call_command("seed_registry", profile="cheap")

    names = set(NodeModelBinding.objects.values_list("model__name", flat=True))
    assert names <= CHEAP_MODELS and names


def test_seed_command_refuses_an_unknown_profile():
    with pytest.raises(CommandError, match="profile"):
        call_command("seed_registry", profile="lavish")


def test_the_strategy_settings_of_models_and_bindings_round_trip_as_plain_json():
    from datetime import date

    RegistrySerializer().load(DefaultRegistry().build())
    LLMModel.objects.filter(name="gemini-3.6-flash").update(shutdown_on=date(2027, 6, 1), tier="T2")
    exported = json.loads(json.dumps(RegistrySerializer().export()))  # a date must survive JSON

    models = {m["name"]: m for m in exported["models"]}
    oss = next(n for n in exported["nodes"] if n["node_key"] == "learner.assess")["bindings"][0]
    assert models["gemini-3.6-flash"]["shutdown_on"] == "2027-06-01"
    assert models["openai/gpt-oss-120b"]["strict_structured"] is True
    assert models["openai/gpt-oss-120b"]["max_request_tokens"] == 6000
    assert models["gemini-3.5-flash-lite"]["reasoning_levels"] == ["minimal", "low", "medium", "high"]
    assert models["gemini-3.5-flash-lite"]["reasoning_off"] == "minimal"
    assert oss["max_output_tokens"] == 4400 and oss["fall_through_on"] == []

    RegistrySerializer().load(exported)
    assert LLMModel.objects.get(name="gemini-3.6-flash").shutdown_on == date(2027, 6, 1)

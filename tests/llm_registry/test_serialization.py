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
- export then import round-trips to the same JSON
- an invalid import rolls back everything
- seed_registry leaves an existing registry alone unless forced
- seed_registry loads an exported file
- seed_registry --profile cheap loads the cheap profile; an unknown profile is refused
"""

import json

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
        "diagnostic.review": ["openai/gpt-oss-20b", "gemini-3.5-flash"],
        "media.verify": ["gemini-3.5-flash", "gemini-3.5-flash-lite"],
        "lesson.plan": ["gemini-3.5-flash", "openai/gpt-oss-120b", "gemini-3.5-flash-lite"],
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

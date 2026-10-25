"""Unit under test: the named seed profiles in `llm_registry.seed` (`SEED_PROFILES`): default, cheap, balanced, quality.

Why: a profile is a whole routing table that the console previews and an admin loads with one command. A profile that
binds a model that cannot serve a node (no vision for the picture check, a Groq model on a reply too big for its free
token cap) would fail lessons, and one that does not describe itself cannot be offered in a list.

Use cases:
- the profiles on offer are default, cheap, balanced and quality, each with a label and a description
- every profile loads, and leaves every enabled node with at least two usable models
- balanced lets Gemini Flash write and judge, and the Flash-Lite models do the mechanical steps, at the nodes' own
  effort
- quality leads every node with Gemini Flash (but the onboarding suggester, which must stay quick), with the nodes'
  reasoning effort one step up
- whatever the profile, the onboarding suggester keeps its quick settings: 4 seconds a call, one attempt, no retry on a
  model, so a learner at step 5 waits for the catalogue after seconds, not minutes
- the heavy steps never lead with a Groq model in the new profiles, and the picture check only uses vision models
"""

import pytest

from llm_registry.models import LLMModel, NodeConfig, NodeModelBinding
from llm_registry.node_specs import NODE_SPECS, Effort
from llm_registry.resolver import RegistryResolver
from llm_registry.seed import SEED_PROFILES
from llm_registry.serialization import RegistrySerializer

pytestmark = pytest.mark.django_db

FLASH, LITE = "gemini-3.5-flash", "gemini-3.5-flash-lite"
HEAVY = ("study.generate", "page.generate", "test.generate", "interactive.generate", "page.compile", "code.repair",
         "runtime.repair")  # fmt: skip
ONBOARDING = "onboarding.suggest_topics"


def test_the_profiles_on_offer_describe_themselves():
    assert list(SEED_PROFILES) == ["default", "cheap", "balanced", "quality"]
    for name, profile in SEED_PROFILES.items():
        assert profile.label and profile.description, name
    assert len({p.label for p in SEED_PROFILES.values()}) == len({p.description for p in SEED_PROFILES.values()}) == 4


@pytest.mark.parametrize("name", list(SEED_PROFILES))
def test_every_profile_loads_and_gives_each_node_a_fallback(name):
    RegistrySerializer().load(SEED_PROFILES[name]().build())

    resolved = RegistryResolver().resolve()
    for node in NodeConfig.objects.filter(is_enabled=True):
        assert len(resolved[node.node_key].chain) >= 2, f"{name}: {node.node_key} has no fallback"


def chain_of(key):
    return [m.model_name for m in RegistryResolver().resolve()[key].chain]


def test_balanced_lets_flash_write_and_judge_and_flash_lite_do_the_mechanical_steps():
    RegistrySerializer().load(SEED_PROFILES["balanced"]().build())

    for key in ("lesson.plan", "page.generate", "test.generate", "alignment.judge", "learner.assess", "test.grade"):
        assert chain_of(key)[0] == FLASH, key
    for key in ("page.compile", "code.repair", "runtime.repair"):
        assert chain_of(key)[0] == LITE, key
    for key in NODE_SPECS:
        if key != ONBOARDING:  # the suggester keeps its own quick settings
            assert NodeConfig.objects.get(node_key=key).reasoning_effort == NODE_SPECS[key].default_reasoning, key


def test_quality_leads_every_node_with_flash_and_raises_the_reasoning_effort_a_step():
    RegistrySerializer().load(SEED_PROFILES["quality"]().build())

    raised = {Effort.NONE: "none", Effort.LOW: "medium", Effort.MEDIUM: "high", Effort.HIGH: "high"}
    for key, spec in NODE_SPECS.items():
        if key == ONBOARDING:
            continue
        assert chain_of(key)[0] == FLASH, key
        assert NodeConfig.objects.get(node_key=key).reasoning_effort == raised[spec.default_reasoning], key
    assert chain_of(ONBOARDING)[0] == "openai/gpt-oss-20b"  # the learner is waiting: still the quick model


@pytest.mark.parametrize("name", list(SEED_PROFILES))
def test_the_onboarding_suggester_keeps_its_four_second_timeout_in_every_profile(name):
    RegistrySerializer().load(SEED_PROFILES[name]().build())

    config = NodeConfig.objects.get(node_key=ONBOARDING)
    bindings = NodeModelBinding.objects.filter(node=config)

    assert (config.max_attempts, config.timeout_s) == (1, 4)
    assert bindings.exists() and set(bindings.values_list("max_retries", flat=True)) == {0}


@pytest.mark.parametrize("name", ["balanced", "quality"])
def test_heavy_steps_never_lead_with_groq_and_the_picture_check_uses_vision_models(name):
    RegistrySerializer().load(SEED_PROFILES[name]().build())

    for key in HEAVY:
        assert RegistryResolver().resolve()[key].chain[0].provider_key == "gemini", key
    vision = LLMModel.objects.filter(name__in=chain_of("media.verify"))
    assert vision and all(m.supports_vision for m in vision)

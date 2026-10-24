import os

import pytest
from django.core.exceptions import ValidationError

from llm_registry.models import LLMModel, NodeModelBinding, Provider

pytestmark = pytest.mark.django_db


def test_binding_refuses_model_without_required_capability(node_configs, llama):
    binding = NodeModelBinding(node=node_configs["media.verify"], model=llama)
    with pytest.raises(ValidationError, match="vision"):
        binding.full_clean()


def test_binding_refuses_model_with_too_small_output(node_configs, llama):
    binding = NodeModelBinding(node=node_configs["page.compile"], model=llama)  # needs 32k; llama has exactly 32768
    binding.full_clean()  # boundary is allowed
    llama.max_output_tokens = 8192
    llama.save()
    with pytest.raises(ValidationError, match="outputs at most"):
        NodeModelBinding(node=node_configs["page.compile"], model=llama).full_clean()


def test_binding_refuses_unsupported_params(node_configs, llama):
    binding = NodeModelBinding(node=node_configs["learner.assess"], model=llama, params_override={"top_k": 5})
    with pytest.raises(ValidationError, match="top_k"):
        binding.full_clean()


def test_capable_binding_passes(node_configs, flash):
    NodeModelBinding(node=node_configs["media.verify"], model=flash).full_clean()


def test_required_node_cannot_be_disabled(node_configs):
    node = node_configs["lesson.plan"]
    node.is_enabled = False
    with pytest.raises(ValidationError, match="required"):
        node.full_clean()


def test_optional_node_can_be_disabled(node_configs):
    node = node_configs["diagnostic.review"]
    node.is_enabled = False
    node.full_clean()


def test_tool_nodes_need_a_step_limit(node_configs):
    node = node_configs["media.search"]
    assert node.max_tool_steps == 6  # from the spec
    node.max_tool_steps = None
    with pytest.raises(ValidationError, match="tool-step"):
        node.full_clean()


def test_reasoning_model_needs_a_control(gemini):
    model = LLMModel(provider=gemini, name="x", supports_reasoning=True, reasoning_control="none")
    with pytest.raises(ValidationError, match="reasoning"):
        model.full_clean()


def test_provider_kinds_and_urls():
    with pytest.raises(ValidationError, match="base_url"):
        Provider(key="local", kind="ollama").full_clean()
    with pytest.raises(ValidationError, match="api_key_env"):
        Provider(key="oa", kind="openai").full_clean()
    Provider(key="local", kind="ollama", base_url="http://localhost:11434").full_clean()


def test_has_api_key_reads_the_environment(gemini, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert not gemini.has_api_key
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert gemini.has_api_key
    assert os.environ["GEMINI_API_KEY"] == "k"

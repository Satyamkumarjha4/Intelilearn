"""Binds the registry to a running fake LLM server (tests/e2e/fake_llm_server.py), the way the throwaway stack does.

`FakeLLMBinding.bind(server, monkeypatch)` creates a provider and a model that point at the server, binds the model to
every node, and returns the registry snapshot to hand to `Gateway().invoke(..., snapshot=...)`. The key is a dummy
value in the environment (the resolver leaves out a layer whose provider has no key).
"""

from llm_registry.models import LLMModel, NodeConfig, NodeModelBinding, Provider
from llm_registry.node_configs import NodeConfigSync
from llm_registry.resolver import RegistryResolver


class FakeLLMBinding:
    @staticmethod
    def bind(server, monkeypatch, method: str = "json_schema", *, vision: bool = False) -> dict:
        monkeypatch.setenv("FAKE_LLM_API_KEY", "not-a-secret")
        NodeConfigSync().ensure()
        provider = Provider.objects.create(
            key="fake", kind="openai_compatible", api_key_env="FAKE_LLM_API_KEY", base_url=server.base_url
        )
        model = LLMModel.objects.create(
            provider=provider,
            name="fake-model",
            supports_structured_output=True,
            structured_output_method=method,
            supports_tool_calling=True,
            supports_vision=vision,
            context_window=1_000_000,
            max_output_tokens=65_536,
        )
        for node in NodeConfig.objects.all():
            NodeModelBinding.objects.create(node=node, model=model, priority=0)
        return RegistryResolver().snapshot().to_json()

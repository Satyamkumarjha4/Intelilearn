"""Builds real LangChain clients (no network) to prove our parameter names match the installed integrations."""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from llm_registry.providers import MissingAPIKey, build_chat_model


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", "sk-test")


def test_gemini_with_thinking_budget(resolved_model):
    model = resolved_model(
        provider_kind="google_genai",
        model_name="gemini-2.5-flash",
        api_key_env="TEST_LLM_KEY",
        params={"temperature": 0.5, "max_tokens": 1000, "top_k": 20},
        reasoning={"thinking_budget": 8192},
    )
    chat = build_chat_model(model, 45)

    assert isinstance(chat, ChatGoogleGenerativeAI)
    assert (chat.temperature, chat.max_output_tokens, chat.top_k, chat.thinking_budget) == (0.5, 1000, 20, 8192)


def test_gemini_with_thinking_level(resolved_model):
    chat = build_chat_model(
        resolved_model(provider_kind="google_genai", model_name="gemini-3-pro", api_key_env="TEST_LLM_KEY",
                       reasoning={"thinking_level": "high"}),
        45,
    )  # fmt: skip
    assert chat.reasoning_effort == "high"


def test_anthropic_effort_and_thinking(resolved_model):
    effort = build_chat_model(
        resolved_model(provider_kind="anthropic", model_name="claude-x", api_key_env="TEST_LLM_KEY",
                       params={"max_tokens": 2000}, reasoning={"effort": "high"}),
        45,
    )  # fmt: skip
    budget = build_chat_model(
        resolved_model(provider_kind="anthropic", model_name="claude-x", api_key_env="TEST_LLM_KEY",
                       params={"max_tokens": 30000}, reasoning={"thinking": {"type": "enabled", "budget_tokens": 24576}}),
        45,
    )  # fmt: skip

    assert isinstance(effort, ChatAnthropic)
    assert effort.reasoning_effort == "high" and effort.max_tokens == 2000
    assert budget.thinking == {"type": "enabled", "budget_tokens": 24576}
    assert effort.max_retries == 0 and effort.default_request_timeout == 45


def test_openai_reasoning_and_limits(resolved_model):
    chat = build_chat_model(
        resolved_model(provider_kind="openai", model_name="gpt-x", api_key_env="TEST_LLM_KEY",
                       params={"max_tokens": 4000, "seed": 7}, reasoning={"reasoning_effort": "low"}),
        45,
    )  # fmt: skip
    assert isinstance(chat, ChatOpenAI)
    assert (chat.reasoning_effort, chat.max_tokens, chat.seed, chat.max_retries) == ("low", 4000, 7, 0)


def test_openai_compatible_uses_base_url(resolved_model):
    chat = build_chat_model(
        resolved_model(provider_kind="openai_compatible", model_name="meta/llama", api_key_env="TEST_LLM_KEY",
                       base_url="https://openrouter.ai/api/v1"),
        45,
    )  # fmt: skip
    assert isinstance(chat, ChatOpenAI)
    assert chat.openai_api_base == "https://openrouter.ai/api/v1"


def test_groq(resolved_model):
    chat = build_chat_model(
        resolved_model(provider_kind="groq", model_name="llama", api_key_env="TEST_LLM_KEY",
                       params={"temperature": 0.2}, reasoning={"reasoning_effort": "medium"}),
        45,
    )  # fmt: skip
    assert isinstance(chat, ChatGroq)
    assert (chat.temperature, chat.reasoning_effort) == (0.2, "medium")


def test_ollama(resolved_model):
    chat = build_chat_model(
        resolved_model(provider_kind="ollama", model_name="qwen3", base_url="http://localhost:11434",
                       params={"max_tokens": 512}, reasoning={"reasoning": True}),
        45,
    )  # fmt: skip
    assert isinstance(chat, ChatOllama)
    assert (chat.num_predict, chat.reasoning, chat.base_url) == (512, True, "http://localhost:11434")


def test_missing_key_is_a_clear_error(resolved_model, monkeypatch):
    monkeypatch.delenv("TEST_LLM_KEY")
    with pytest.raises(MissingAPIKey, match="TEST_LLM_KEY"):
        build_chat_model(resolved_model(provider_kind="openai", api_key_env="TEST_LLM_KEY"), 45)

"""Build LangChain chat models from resolved registry entries (Factory)."""

import os
from typing import Protocol

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from .profiles import PROVIDER_PROFILES, ProviderProfiles
from .resolver import ResolvedModel


class MissingAPIKey(RuntimeError):
    pass


class ChatModelFactory(Protocol):
    """Anything that turns a ResolvedModel into a chat model; tests pass a plain function returning a fake."""

    def __call__(self, model: ResolvedModel, timeout_s: int) -> BaseChatModel: ...


class LangChainChatModelFactory:
    def __init__(self, profiles: ProviderProfiles = PROVIDER_PROFILES, environ=None):
        self._profiles = profiles
        self._environ = environ

    def __call__(self, model: ResolvedModel, timeout_s: int) -> BaseChatModel:
        profile = self._profiles.for_kind(model.provider_kind)
        kwargs = {**profile.to_integration_kwargs(model.params), **model.reasoning}

        if model.api_key_env:
            environ = self._environ if self._environ is not None else os.environ
            api_key = environ.get(model.api_key_env)
            if not api_key:
                raise MissingAPIKey(f"Environment variable {model.api_key_env} is not set (needed by {model.label}).")
            kwargs["api_key"] = api_key
        if model.base_url:
            kwargs["base_url"] = model.base_url
        if profile.supports_client_timeout:
            kwargs["timeout"] = timeout_s
            kwargs["max_retries"] = 0  # the gateway owns retries and fallbacks

        return init_chat_model(model.model_name, model_provider=profile.langchain_provider, **kwargs)


# The real factory; the gateway, probes and probe_models default to it (tests patch or inject their own).
CHAT_MODEL_FACTORY = LangChainChatModelFactory()

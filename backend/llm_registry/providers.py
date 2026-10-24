"""Build LangChain chat models from resolved registry entries."""

import os

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from .profiles import PROVIDER_PROFILES
from .resolver import ResolvedModel


class MissingAPIKey(RuntimeError):
    pass


def build_chat_model(model: ResolvedModel, timeout_s: int) -> BaseChatModel:
    profile = PROVIDER_PROFILES.for_kind(model.provider_kind)
    kwargs = {**profile.to_integration_kwargs(model.params), **model.reasoning}

    if model.api_key_env:
        api_key = os.environ.get(model.api_key_env)
        if not api_key:
            raise MissingAPIKey(f"Environment variable {model.api_key_env} is not set (needed by {model.label}).")
        kwargs["api_key"] = api_key
    if model.base_url:
        kwargs["base_url"] = model.base_url
    if profile.supports_client_timeout:
        kwargs["timeout"] = timeout_s
        kwargs["max_retries"] = 0  # the gateway owns retries and fallbacks

    return init_chat_model(model.model_name, model_provider=profile.langchain_provider, **kwargs)

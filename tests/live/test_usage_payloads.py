"""Live: one real reply from each provider with a key, and the raw token usage it reported.

Run by hand (`pytest -m live tests/live/test_usage_payloads.py -s`): it spends a fraction of a cent per provider. It
builds each client the way the gateway does (the registry's own parameter names, so a wrong name fails here and not in
a lesson), asks for a few words of thinking, and prints the usage payload: LangChain's `usage_metadata` and the
provider's own. Read the printout to settle the "(unverified)" token fields of the model strategy: whether the output
tokens include the thinking tokens, whether the input tokens include the cached ones, and the field names.

Use cases:
- a provider with a key answers, and its reply carries integer input and output tokens
- the reply's usage is printed in full, once per provider
- a provider without a key is skipped with the variable's name
"""

import os

import pytest
from live.usage_payloads import UsagePayload

from llm_registry.profiles import PROVIDER_PROFILES
from llm_registry.providers import LangChainChatModelFactory
from llm_registry.resolver import ResolvedModel

pytestmark = pytest.mark.live

# provider key, kind, key variable, a cheap model, whether the model reasons, how "a little thinking" is asked for
PROVIDERS = [
    ("gemini", "google_genai", "GEMINI_API_KEY", "gemini-3.1-flash-lite", "effort",
     ["minimal", "low", "medium", "high"]),
    ("groq", "groq", "GROQ_API_KEY", "openai/gpt-oss-20b", "effort", ["low", "medium", "high"]),
    ("openai", "openai", "OPENAI_API_KEY", "gpt-6-luna", "effort", ["low", "medium", "high"]),
    ("anthropic", "anthropic", "ANTHROPIC_API_KEY", "claude-haiku-5-5", "effort", ["low", "medium", "high"]),
]  # fmt: skip
ASK = "Think briefly, then reply with the single word: ok"


@pytest.mark.parametrize(("provider", "kind", "variable", "model", "control", "levels"), PROVIDERS,
                         ids=[p[0] for p in PROVIDERS])  # fmt: skip
def test_a_real_reply_reports_its_token_usage(provider, kind, variable, model, control, levels, capsys):
    if not os.environ.get(variable):
        pytest.skip(f"{variable} is not set")
    profile = PROVIDER_PROFILES.for_kind(kind)
    params, reasoning = profile.apply_reasoning(control, "low", {"max_tokens": 600}, disables_sampling=False,
                                                levels=levels)  # fmt: skip
    resolved = ResolvedModel(provider_key=provider, provider_kind=kind, model_name=model, params=params,
                             reasoning=reasoning, reasoning_effort="low", structured_output_method="json_schema",
                             api_key_env=variable, base_url="", max_retries=0)  # fmt: skip

    reply = LangChainChatModelFactory()(resolved, 60).invoke(ASK)

    payload = UsagePayload.of(reply)
    with capsys.disabled():
        print("\n" + UsagePayload.text(provider, model, payload))
    assert UsagePayload.findings(payload, thinking_asked=False) == []

"""Unit under test: `llm_registry.redaction.Redactor`, which masks credentials in text before it is stored or shown.

Why: provider SDK errors can echo request details. Anything unmasked lands in ModelCall.error, admin messages,
progress events sent to the browser and probe output, which would leak a paid API key.

Use cases:
- masks the values of configured secret environment variables
- masks well-known key formats even when they aren't configured
- masks bearer tokens
- leaves ordinary text (and too-short "secrets") untouched
- uses an injected environment instead of os.environ
- the gateway redacts AllModelsFailed errors
- the gateway redacts the reason in fallback events
"""

import pytest
from langchain_core.messages import AIMessage

from llm_registry.gateway import AllModelsFailed
from llm_registry.redaction import REDACTOR, Redactor

MASK = Redactor.MASK
redact = REDACTOR.redact


class NoRateLimit:
    def acquire(self, limits):
        return 0


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "my-real-gemini-key-123")
    monkeypatch.setenv("SHORT_TOKEN", "abc")  # too short to be a real secret; left alone


def test_configured_key_values_are_masked():
    assert redact("401 for key my-real-gemini-key-123 on request") == f"401 for key {MASK} on request"


def test_known_key_formats_are_masked_even_if_not_configured():
    text = "keys: AIzaSyA1234567890abcdefghijklmnopqrstuv gsk_abcdefghijklmnopqrstuvwx sk-ant-abcdefghijklmnopqrstuv"
    assert redact(text) == f"keys: {MASK} {MASK} {MASK}"


def test_bearer_tokens_are_masked():
    assert redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig") == f"Authorization: {MASK}"


def test_ordinary_text_is_untouched():
    assert redact("Rate limit exceeded (429), retry in 7s; abc") == "Rate limit exceeded (429), retry in 7s; abc"


def test_an_injected_environment_is_used_instead_of_os_environ():
    redactor = Redactor(environ={"OTHER_API_KEY": "injected-secret-value"})
    assert redactor.redact("key injected-secret-value; my-real-gemini-key-123") == f"key {MASK}; my-real-gemini-key-123"


def test_gateway_errors_are_redacted():
    error = AllModelsFailed("learner.assess", ["gemini/x: invalid key my-real-gemini-key-123"])
    assert "my-real-gemini-key-123" not in str(error)
    assert MASK in error.errors[0]


@pytest.mark.django_db
def test_fallback_event_reason_is_redacted(resolved_model, make_snapshot, FakeChat):
    from langchain_core.messages import HumanMessage
    from pydantic import BaseModel

    from llm_registry.gateway import Gateway

    class Answer(BaseModel):
        value: int

    class Unauthorized(Exception):
        status_code = 401

    ok = {"raw": AIMessage(content=""), "parsed": Answer(value=1), "parsing_error": None}
    fakes = {"a": FakeChat(Unauthorized("bad key my-real-gemini-key-123")), "b": FakeChat(ok)}
    events = []
    snapshot = make_snapshot("learner.assess", "structured", [resolved_model("a"), resolved_model("b")])
    Gateway(lambda m, t: fakes[m.model_name], sleep=lambda s: None, limiter=NoRateLimit()).invoke(
        "learner.assess", [HumanMessage("hi")], snapshot=snapshot, schema=Answer, on_event=events.append
    )

    assert "my-real-gemini-key-123" not in events[0]["reason"]

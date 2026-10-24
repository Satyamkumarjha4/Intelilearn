import pytest
from django.core.management import CommandError, call_command
from langchain_core.messages import AIMessage

from llm_registry.models import ModelCall
from llm_registry.seed import default_registry
from llm_registry.serialization import import_registry

pytestmark = pytest.mark.django_db


class Chat:
    """Answers every probe and gateway call; `fail=True` makes plain calls raise."""

    def __init__(self, fail=False):
        self.fail = fail

    def invoke(self, messages):
        if self.fail:
            raise RuntimeError("401 invalid key gsk_abcdefghijklmnopqrstuvwxyz")
        return AIMessage(content="pong")

    def with_structured_output(self, schema, method=None, include_raw=False):
        fields = {"ok": True, "word": "pong"} if "ok" in schema.model_fields else {"word": "pong"}

        class Runnable:
            def invoke(self, messages):
                return {"raw": AIMessage(content=""), "parsed": schema(**fields), "parsing_error": None}

        return Runnable()

    def bind_tools(self, tools):
        class Runnable:
            def invoke(self, messages):
                return AIMessage(content="", tool_calls=[{"name": "get_server_time", "args": {}, "id": "1"}])

        return Runnable()


@pytest.fixture
def seeded():
    import_registry(default_registry())


def test_probes_the_given_model_and_runs_a_node(seeded, monkeypatch, capsys):
    monkeypatch.setattr("llm_registry.providers.CHAT_MODEL_FACTORY", lambda model, timeout: Chat())

    call_command("probe_models", model=["groq/llama-3.3-70b-versatile"], node=["learner.assess"])

    out = capsys.readouterr().out
    assert "✔ tool_calling" in out
    assert "answered by gemini/gemini-2.5-flash (fallback #0" in out
    assert "All checks passed" in out
    assert ModelCall.objects.filter(node_key="learner.assess", status="ok").exists()


def test_failures_exit_non_zero_with_keys_redacted(seeded, monkeypatch, capsys):
    monkeypatch.setattr("llm_registry.providers.CHAT_MODEL_FACTORY", lambda model, timeout: Chat(fail=True))

    with pytest.raises(CommandError, match="failed"):
        call_command("probe_models", model=["groq/llama-3.3-70b-versatile"])

    out = capsys.readouterr().out
    assert "✘ text" in out
    assert "gsk_" not in out


def test_unknown_model_is_a_clear_error(seeded):
    with pytest.raises(CommandError, match="provider/name"):
        call_command("probe_models", model=["nope/missing"])

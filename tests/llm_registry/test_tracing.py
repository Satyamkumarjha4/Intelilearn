"""Unit under test: `llm_registry.tracing` (`NoTracing`, `LangSmithTracing`, `LangfuseTracing`, `SafeTracing`,
`TracingProviders`) and how the `Gateway` passes the result to each model call.

Why: a trace holds the prompts and replies, which contain what the learner wrote, so tracing must be off unless an
operator asks for it and must go only to the service they chose. And an observability feature must never be the reason
a lesson fails: a missing package or a broken tracer has to cost a trace, not a model call.

Use cases:
- no tracing gives a call no config at all, so the model is invoked exactly as before
- LangSmith and Langfuse give each call callbacks, a run name, tags and metadata (node, model, lesson, run)
- the LangSmith project comes from the argument, then the environment, then a default
- Langfuse without its package says how to install it; its handler is created when first needed
- a provider that raises costs a trace, once logged, and never a call
- providers are chosen by name (any case), an unknown name says which are known, and settings pick the default
- the gateway passes the config on every attempt, including retries, and nothing when there is none
"""

import logging
import sys
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from llm_registry.gateway import Gateway
from llm_registry.tracing import (
    LangfuseTracing,
    LangSmithTracing,
    NoTracing,
    SafeTracing,
    TracingNotAvailable,
    TracingProviders,
)

pytestmark = pytest.mark.django_db

CALL = {"node_key": "learner.assess", "model": "fake/primary", "lesson_id": "L-1", "run_id": "R-1"}


class FakeTracer:
    def __init__(self, project_name):
        self.project_name = project_name


class FakeHandler:
    pass


class TestNoTracing:
    def test_a_call_gets_no_config(self):
        assert NoTracing().config(**CALL) == {}


class TestLangSmith:
    def test_a_call_gets_a_tracer_for_the_project_and_describes_itself(self):
        config = LangSmithTracing(project="my-project", tracer=FakeTracer).config(**CALL)

        assert [c.project_name for c in config["callbacks"]] == ["my-project"]
        assert config["run_name"] == "learner.assess" and config["tags"] == ["learner.assess"]
        assert config["metadata"] == {
            "node_key": "learner.assess",
            "model": "fake/primary",
            "lesson_id": "L-1",
            "run_id": "R-1",
        }

    def test_the_project_falls_back_to_the_environment_then_a_default(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_PROJECT", "from-env")
        assert LangSmithTracing().project == "from-env"

        monkeypatch.delenv("LANGSMITH_PROJECT")
        assert LangSmithTracing().project == "lesson-crafter"

    def test_the_real_tracer_is_langchains_and_needs_no_new_package(self):
        config = LangSmithTracing(project="p").config(**CALL)

        assert type(config["callbacks"][0]).__name__ == "LangChainTracer"

    def test_missing_ids_become_empty_strings(self):
        config = LangSmithTracing(tracer=FakeTracer).config(**(CALL | {"lesson_id": None, "run_id": None}))

        assert config["metadata"]["lesson_id"] == "" and config["metadata"]["run_id"] == ""


class TestLangfuse:
    def test_a_call_gets_a_handler_and_the_session_and_tags(self):
        config = LangfuseTracing(handler=FakeHandler).config(**CALL)

        assert [type(c) for c in config["callbacks"]] == [FakeHandler]
        assert config["metadata"]["langfuse_session_id"] == "L-1" and config["metadata"]["langfuse_tags"] == [
            "learner.assess"
        ]
        assert config["run_name"] == "learner.assess"

    def test_each_call_gets_its_own_handler(self):
        tracing = LangfuseTracing(handler=FakeHandler)

        assert tracing.config(**CALL)["callbacks"][0] is not tracing.config(**CALL)["callbacks"][0]

    def test_without_its_package_it_says_how_to_install_it(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "langfuse", None)
        monkeypatch.setitem(sys.modules, "langfuse.langchain", None)

        with pytest.raises(TracingNotAvailable, match="uv add langfuse"):
            LangfuseTracing().config(**CALL)

    def test_the_real_handler_is_used_when_the_package_is_there(self, monkeypatch):
        module = SimpleNamespace(CallbackHandler=FakeHandler)
        monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(langchain=module))
        monkeypatch.setitem(sys.modules, "langfuse.langchain", module)

        assert [type(c) for c in LangfuseTracing().config(**CALL)["callbacks"]] == [FakeHandler]


class TestSafeTracing:
    class Broken:
        def config(self, **call):
            raise RuntimeError("tracing service unreachable")

    def test_a_provider_that_raises_costs_a_trace_not_a_call(self):
        assert SafeTracing(self.Broken()).config(**CALL) == {}

    def test_the_problem_is_logged_once(self, caplog):
        tracing = SafeTracing(self.Broken())

        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                tracing.config(**CALL)

        assert [r.message for r in caplog.records].count(
            "Tracing is switched off for this process: tracing service unreachable"
        ) == 1

    def test_a_working_provider_passes_through(self):
        assert SafeTracing(LangfuseTracing(handler=FakeHandler)).config(**CALL)["run_name"] == "learner.assess"


class TestProviders:
    @pytest.mark.parametrize(
        ("name", "kind"),
        [("none", NoTracing), ("", NoTracing), ("LangSmith", LangSmithTracing), (" langfuse ", LangfuseTracing)],
    )
    def test_a_provider_is_chosen_by_name_in_any_case(self, name, kind):
        assert isinstance(TracingProviders.for_name(name), kind)

    def test_an_unknown_name_says_which_are_known(self):
        with pytest.raises(TracingNotAvailable, match="'zipkin' is not one of none, langsmith, langfuse"):
            TracingProviders.for_name("zipkin")

    def test_settings_choose_the_default_and_it_cannot_fail_a_call(self, settings):
        settings.LLM_TRACING = "langsmith"

        provider = TracingProviders.from_settings()

        assert isinstance(provider, SafeTracing) and isinstance(provider.provider, LangSmithTracing)

    def test_the_default_is_no_tracing(self, settings):
        settings.LLM_TRACING = "none"

        assert isinstance(TracingProviders.from_settings().provider, NoTracing)

    def test_an_unknown_name_in_settings_means_no_tracing_and_a_log_line(self, settings, caplog):
        settings.LLM_TRACING = "zipkin"

        with caplog.at_level(logging.WARNING):
            provider = TracingProviders.from_settings()

        assert isinstance(provider, NoTracing) and "Tracing is off" in caplog.text


class Answer(BaseModel):
    value: int


def reply(value=1):
    raw = AIMessage(content="", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
    return {"raw": raw, "parsed": Answer(value=value), "parsing_error": None}


class RateLimited(Exception):
    status_code = 429


class NoLimit:
    def acquire(self, limits):
        return 0


class RecordingTracing:
    def __init__(self, config):
        self.calls, self._config = [], config

    def config(self, **call):
        self.calls.append(call)
        return self._config


class TestGateway:
    def invoke(self, FakeChat, resolved_model, make_snapshot, tracing, *script):
        chat = FakeChat(*script)
        snapshot = make_snapshot("learner.assess", "structured", [resolved_model("primary")])
        gateway = Gateway(lambda model, timeout: chat, sleep=lambda s: None, limiter=NoLimit(), tracing=tracing)
        gateway.invoke(
            "learner.assess", [HumanMessage("hi")], snapshot=snapshot, schema=Answer, lesson_id="L-1", run_id="R-1"
        )
        return chat

    def test_the_config_is_passed_to_the_model_and_describes_the_call(self, FakeChat, resolved_model, make_snapshot):
        tracing = RecordingTracing({"run_name": "learner.assess"})

        chat = self.invoke(FakeChat, resolved_model, make_snapshot, tracing, reply())

        assert chat.configs == [{"run_name": "learner.assess"}]
        assert tracing.calls == [
            {"node_key": "learner.assess", "model": "fake/primary", "lesson_id": "L-1", "run_id": "R-1"}
        ]

    def test_every_attempt_is_traced_including_a_retry(self, FakeChat, resolved_model, make_snapshot):
        tracing = RecordingTracing({"run_name": "x"})

        chat = self.invoke(FakeChat, resolved_model, make_snapshot, tracing, RateLimited("slow"), reply())

        assert chat.configs == [{"run_name": "x"}, {"run_name": "x"}]

    def test_without_tracing_the_model_is_invoked_without_a_config(self, FakeChat, resolved_model, make_snapshot):
        chat = self.invoke(FakeChat, resolved_model, make_snapshot, NoTracing(), reply())

        assert chat.configs == [None]

    def test_the_default_gateway_does_not_trace(self, FakeChat, resolved_model, make_snapshot, settings):
        settings.LLM_TRACING = "none"
        chat = FakeChat(reply())
        snapshot = make_snapshot("learner.assess", "structured", [resolved_model("primary")])

        Gateway(lambda model, timeout: chat, sleep=lambda s: None, limiter=NoLimit()).invoke(
            "learner.assess", [HumanMessage("hi")], snapshot=snapshot, schema=Answer
        )

        assert chat.configs == [None]

    def test_a_tracer_that_fails_does_not_fail_the_call(self, FakeChat, resolved_model, make_snapshot):
        tracing = SafeTracing(TestSafeTracing.Broken())

        chat = self.invoke(FakeChat, resolved_model, make_snapshot, tracing, reply(5))

        assert chat.configs == [None]

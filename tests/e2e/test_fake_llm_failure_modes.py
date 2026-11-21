"""Unit under test: the failure modes of the fake LLM server (tests/e2e/fake_failures.py), met by the real `Gateway`,
the real LangChain client and the real validators.

Why: the fallback layers and the refund paths only run when a model fails, and a real provider will not fail on cue.
The audit (and any browser test) asks the fake to fail, so each mode has to look to the gateway exactly like the
real failure it stands for: a reply that is not JSON fails the client's parse, a 429 is retried, a 401 is fatal and
trips the provider's breaker, a reply that outlasts the timeout is retried, and a reply the validators refuse is a
valid reply as far as the gateway is concerned (judging it is the graph's job).

Use cases:
- invalid_json: the reply cannot be parsed, so the real client raises a validation error that the gateway logs as a
  fatal error (it does not ask again on this client path); with one model every model fails, and a second model bound
  behind the first answers, which is the fallback layer exercised
- rate_limit once: a retryable error is logged and the retry gets the answer; on every call the retries run out
- unauthorized: a fatal error after one try (no retry) and every model fails; after three in a row the provider's
  breaker opens, so the next call is skipped without reaching the server
- timeout: a reply that takes longer than the node's timeout is a retryable error, and the retry gets the answer
- rejected: the reply is a valid DiagnosticBundle that the real DiagnosticValidator refuses, and the next call is a
  good bundle
- a rule for another schema changes nothing, and the plan counts the calls the server served and failed
- the rejected mode for a schema with no rejected variant is a 400 that says so (not a silent success)
"""

import time

import pytest
from e2e.fake_failures import FAILURES
from e2e.fake_llm_server import FakeLLMServer
from pydantic import BaseModel
from support.fake_llm import FakeLLMBinding

from graph.prompts import DiagnosticPrompt
from graph.schemas import DiagnosticBundle, QuizReview
from graph.validators import DiagnosticValidator
from llm_registry.gateway import AllModelsFailed, Gateway
from llm_registry.models import LLMModel, ModelCall, NodeConfig, NodeModelBinding, Provider
from llm_registry.resolver import RegistryResolver

pytestmark = pytest.mark.django_db

STATE = {"topic": "Binary search", "settings": {}, "profile": {}}
NODE = "diagnostic.generate"


@pytest.fixture
def server():
    with FakeLLMServer() as running:
        yield running


@pytest.fixture
def snapshot(server, monkeypatch) -> dict:
    return FakeLLMBinding.bind(server, monkeypatch)


def ask(snapshot: dict, schema: type[BaseModel] = DiagnosticBundle, node: str = NODE):
    messages = DiagnosticPrompt().messages(STATE) if schema is DiagnosticBundle else []
    return Gateway(sleep=lambda seconds: None).invoke(node, messages, snapshot=snapshot, schema=schema)


def statuses() -> list[str]:
    return list(ModelCall.objects.filter(node_key=NODE).order_by("id").values_list("status", flat=True))


class TestInvalidJson:
    def test_with_one_model_every_model_fails_and_the_log_says_fatal(self, server, snapshot):
        server.failures.add("invalid_json", schema="DiagnosticBundle", times=-1)

        with pytest.raises(AllModelsFailed, match="Invalid JSON"):
            ask(snapshot)

        assert statuses() == ["fatal_error"]  # no second try on this client path

    def test_a_second_model_behind_the_first_answers(self, server, snapshot):
        provider = Provider.objects.get(key="fake")
        second = LLMModel.objects.create(
            provider=provider,
            name="fake-model-2",
            supports_structured_output=True,
            structured_output_method="json_schema",
            supports_tool_calling=True,
            context_window=1_000_000,
            max_output_tokens=65_536,
        )
        NodeModelBinding.objects.create(node=NodeConfig.objects.get(node_key=NODE), model=second, priority=1)
        server.failures.add("invalid_json", schema="DiagnosticBundle", times=1)

        result = ask(RegistryResolver().snapshot().to_json())

        assert isinstance(result.output, DiagnosticBundle) and result.model.model_name == "fake-model-2"
        assert statuses() == ["fatal_error", "ok"]


class TestRateLimit:
    def test_once_it_is_retried_and_the_retry_gets_the_answer(self, server, snapshot):
        server.failures.add("rate_limit", schema="DiagnosticBundle", times=1)

        result = ask(snapshot)

        assert isinstance(result.output, DiagnosticBundle)
        assert statuses() == ["retryable_error", "ok"]

    def test_on_every_call_the_retries_run_out_and_every_model_fails(self, server, snapshot):
        server.failures.add("rate_limit", schema="DiagnosticBundle", times=-1)

        with pytest.raises(AllModelsFailed):
            ask(snapshot)

        logged = statuses()
        assert len(logged) >= 2 and set(logged) == {"retryable_error"}


class TestUnauthorized:
    def test_it_is_fatal_after_one_try_and_after_three_the_breaker_keeps_the_next_call_from_the_server(
        self, server, snapshot
    ):
        server.failures.add("unauthorized", times=-1)

        for _ in range(3):
            with pytest.raises(AllModelsFailed):
                ask(snapshot)
        assert statuses() == ["fatal_error"] * 3  # one try each: a 401 is not retried
        served = server.failures.snapshot()["calls"]["DiagnosticBundle"]

        with pytest.raises(AllModelsFailed, match="skipped"):
            ask(snapshot)

        assert server.failures.snapshot()["calls"]["DiagnosticBundle"] == served  # the breaker kept the call away


class TestTimeout:
    def test_a_reply_slower_than_the_nodes_timeout_is_retried_and_the_retry_gets_the_answer(self, server, snapshot):
        snapshot["nodes"][NODE]["timeout_s"] = 1
        server.failures.add("timeout", schema="DiagnosticBundle", times=1, delay_s=2.5)
        started = time.monotonic()

        result = ask(snapshot)

        assert isinstance(result.output, DiagnosticBundle)
        assert statuses() == ["retryable_error", "ok"]
        assert time.monotonic() - started < 2.4  # the client gave up at its own timeout, not at the server's pace


class TestRejected:
    def test_the_reply_is_a_valid_bundle_the_real_validator_refuses_and_the_next_one_is_good(self, server, snapshot):
        server.failures.add("rejected", schema="DiagnosticBundle", times=1)

        bad = ask(snapshot)
        good = ask(snapshot)

        assert statuses() == ["ok", "ok"]  # the gateway cannot tell: judging a reply is the graph's job
        problems = DiagnosticValidator().validate(bad.output.model_dump(), settings={})
        assert any("options must all be different" in problem for problem in problems)
        assert DiagnosticValidator().validate(good.output.model_dump(), settings={}) == []

    def test_a_schema_with_no_rejected_variant_is_a_400_that_says_so(self, server, snapshot):
        server.failures.add("rejected", schema="QuizReview", times=1)

        with pytest.raises(AllModelsFailed, match="no rejected variant"):
            ask(snapshot, QuizReview, "diagnostic.review")


class TestPlan:
    def test_a_rule_for_another_schema_changes_nothing_and_the_plan_counts_the_calls(self, server, snapshot):
        server.failures.add("unauthorized", schema="PageContent", times=-1)

        result = ask(snapshot)

        assert isinstance(result.output, DiagnosticBundle)
        plan = server.failures.snapshot()
        assert plan["calls"] == {"DiagnosticBundle": 1} and plan["failed"] == {}

    def test_every_failure_mode_has_a_test_here(self):
        assert sorted(FAILURES) == ["invalid_json", "rate_limit", "rejected", "timeout", "unauthorized"]

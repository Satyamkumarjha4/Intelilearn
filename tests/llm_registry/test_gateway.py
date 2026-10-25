"""Unit under test: `llm_registry.gateway.Gateway`, the one way graph nodes call an LLM: it walks a node's model
chain with retries, schema repair, fallbacks, rate limits and call logging. Driven with scripted fake chat models.

Why: every lesson step goes through it. A wrong retry or fallback decision either fails a lesson a working fallback
could have finished, or burns the time budget retrying an error that can't succeed; a missing log row hides which
model actually answered and what it cost.

Use cases:
- the primary model answers, and the call is logged with its tokens
- a transient error is retried on the same model with backoff
- exhausted retries fall back to the next model, with a fallback event
- a spent daily quota (429) skips straight to the fallback, without retrying or sleeping
- a fatal error skips straight to the fallback
- an invalid structured reply gets one repair attempt with the parse error
- a second invalid reply moves to the next model
- a reply with no parsed output counts as invalid
- when every model fails, AllModelsFailed carries every error
- a model that can't even be built (missing key) falls back
- text nodes return the text; tool nodes return the message with its tool calls
- a disabled node is refused; a structured node without a schema is a programming error
- the rate limiter is asked before each call, per provider and per model
- the time a call waited for a rate-limit window is logged on its ModelCall row, and is zero when it did not wait
- cost is computed from the model's prices
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from llm_registry.gateway import AllModelsFailed, Gateway, NodeDisabled
from llm_registry.models import ModelCall
from llm_registry.providers import MissingAPIKey

pytestmark = pytest.mark.django_db

MESSAGES = [HumanMessage("hello")]


class Answer(BaseModel):
    value: int


class NoRateLimit:
    def acquire(self, limits):
        return 0


class RecordingLimiter:
    def __init__(self, seen):
        self.seen = seen

    def acquire(self, limits):
        self.seen.append(limits)
        return 0


class RateLimited(Exception):
    status_code = 429


class Unauthorized(Exception):
    status_code = 401


def ok(value=1, **usage):
    raw = AIMessage(content="", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, **usage})
    return {"raw": raw, "parsed": Answer(value=value), "parsing_error": None}


def bad(error="value: field required"):
    return {"raw": AIMessage(content='{"nope": 1}'), "parsed": None, "parsing_error": ValueError(error)}


@pytest.fixture
def run(resolved_model, make_snapshot):
    """Run the gateway for a structured node with fake models; returns (result_or_exception, fakes, sleeps, events)."""

    def _run(scripts: dict, *, output="structured", schema=Answer, tools=None, retries=2, enabled=True):
        fakes = scripts
        chain = [resolved_model(name, max_retries=retries) for name in scripts]
        snapshot = make_snapshot("learner.assess", output, chain, enabled=enabled)
        sleeps, events = [], []
        gateway = Gateway(lambda model, timeout: fakes[model.model_name], sleep=sleeps.append, limiter=NoRateLimit())
        try:
            result = gateway.invoke(
                "learner.assess", MESSAGES, snapshot=snapshot, schema=schema, tools=tools, on_event=events.append
            )
        except Exception as exc:  # returned so tests can assert on it
            result = exc
        return result, sleeps, events

    return _run


def test_primary_answers(run, FakeChat):
    primary = FakeChat(ok(7))

    result, sleeps, events = run({"primary": primary})

    assert result.output == Answer(value=7)
    assert result.fallback_index == 0 and result.attempts == 1
    assert primary.structured == (Answer, "json_schema", True)
    call = ModelCall.objects.get()
    assert (call.status, call.input_tokens, call.output_tokens) == ("ok", 10, 5)
    assert sleeps == [] and events == []


def test_transient_error_is_retried_on_same_model(run, FakeChat):
    primary = FakeChat(RateLimited("slow down"), ok(3))

    result, sleeps, events = run({"primary": primary})

    assert result.output.value == 3
    assert result.attempts == 2
    assert len(sleeps) == 1
    assert events[0]["type"] == "retrying"
    assert list(ModelCall.objects.order_by("id").values_list("status", flat=True)) == ["retryable_error", "ok"]


def test_retries_exhausted_falls_back(run, FakeChat):
    primary = FakeChat(RateLimited(), RateLimited(), RateLimited())
    fallback = FakeChat(ok(9))

    result, sleeps, events = run({"primary": primary, "fallback": fallback})

    assert result.output.value == 9
    assert result.fallback_index == 1
    assert len(primary.calls) == 3  # 1 try + 2 retries
    assert [e["type"] for e in events] == ["retrying", "retrying", "fallback_model"]


def test_spent_daily_quota_falls_back_without_retrying(run, FakeChat):
    primary = FakeChat(RateLimited("Rate limit reached on requests per day (RPD): Limit 1000"))
    fallback = FakeChat(ok(4))

    result, sleeps, events = run({"primary": primary, "fallback": fallback})

    assert result.output.value == 4 and result.fallback_index == 1
    assert len(primary.calls) == 1 and sleeps == []
    assert [e["type"] for e in events] == ["fallback_model"]


def test_fatal_error_skips_straight_to_fallback(run, FakeChat):
    primary = FakeChat(Unauthorized("bad key"))
    fallback = FakeChat(ok())

    result, sleeps, _ = run({"primary": primary, "fallback": fallback})

    assert result.fallback_index == 1
    assert len(primary.calls) == 1 and sleeps == []


def test_invalid_output_gets_one_repair_with_the_error(run, FakeChat):
    primary = FakeChat(bad("value: field required"), ok(5))

    result, _, _ = run({"primary": primary})

    assert result.output.value == 5
    repair_prompt = primary.calls[1][-1].content
    assert "did not match the required schema" in repair_prompt
    assert "value: field required" in repair_prompt
    assert primary.calls[1][-2].content == '{"nope": 1}'


def test_invalid_output_twice_moves_to_next_model(run, FakeChat):
    primary = FakeChat(bad(), bad())
    fallback = FakeChat(ok(2))

    result, _, _ = run({"primary": primary, "fallback": fallback})

    assert result.output.value == 2
    assert result.fallback_index == 1
    assert ModelCall.objects.filter(status="invalid_output").count() == 2


def test_missing_parsed_output_counts_as_invalid(run, FakeChat):
    empty = {"raw": AIMessage(content="sorry"), "parsed": None, "parsing_error": None}
    primary = FakeChat(empty, ok())

    result, _, _ = run({"primary": primary})

    assert result.attempts == 1  # the repair round doesn't consume a transport retry


def test_all_models_failing_raises_with_every_error(run, FakeChat):
    result, _, _ = run({"a": FakeChat(Unauthorized("no")), "b": FakeChat(Unauthorized("nope"))})

    assert isinstance(result, AllModelsFailed)
    assert len(result.errors) == 2 and "a:" in result.errors[0]


def test_building_the_model_can_fail_and_fall_back(resolved_model, make_snapshot, FakeChat):
    fallback = FakeChat(ok())

    def factory(model, timeout):
        if model.model_name == "keyless":
            raise MissingAPIKey("GEMINI_API_KEY is not set")
        return fallback

    snapshot = make_snapshot("learner.assess", "structured", [resolved_model("keyless"), resolved_model("fallback")])
    result = Gateway(factory, sleep=lambda s: None, limiter=NoRateLimit()).invoke(
        "learner.assess", MESSAGES, snapshot=snapshot, schema=Answer
    )

    assert result.fallback_index == 1
    assert ModelCall.objects.filter(status="fatal_error", error__contains="GEMINI_API_KEY").exists()


def test_text_output_returns_the_text(run, FakeChat):
    result, _, _ = run(
        {"primary": FakeChat(AIMessage(content="function LessonComponent() {}"))}, output="text", schema=None
    )

    assert result.output == "function LessonComponent() {}"


def test_tool_output_returns_the_message_with_tool_calls(run, FakeChat):
    reply = AIMessage(content="", tool_calls=[{"name": "search_wikimedia", "args": {"query": "amoeba"}, "id": "1"}])
    primary = FakeChat(reply)

    result, _, _ = run({"primary": primary}, output="tools", schema=None, tools=["search_wikimedia"])

    assert result.output.tool_calls[0]["args"] == {"query": "amoeba"}
    assert primary.tools == ["search_wikimedia"]
    assert ModelCall.objects.get().tool_calls == 1


def test_disabled_node_is_refused(run, FakeChat):
    result, _, _ = run({"primary": FakeChat(ok())}, enabled=False)
    assert isinstance(result, NodeDisabled)


def test_structured_node_without_schema_is_a_programming_error(run, FakeChat):
    result, _, _ = run({"primary": FakeChat(ok())}, schema=None)
    assert isinstance(result, ValueError)


def test_rate_limiter_is_asked_before_each_call(resolved_model, make_snapshot, FakeChat):
    seen = []
    snapshot = make_snapshot("learner.assess", "structured", [resolved_model("m", provider_rpm=15, model_rpm=5)])
    Gateway(lambda m, t: FakeChat(ok()), sleep=lambda s: None, limiter=RecordingLimiter(seen)).invoke(
        "learner.assess", MESSAGES, snapshot=snapshot, schema=Answer
    )
    assert seen == [{"provider:fake": 15, "model:fake/m": 5}]


def test_cost_is_computed_from_model_prices(resolved_model, make_snapshot, FakeChat):
    model = resolved_model("m", input_cost_per_mtok=1.0, output_cost_per_mtok=4.0)
    snapshot = make_snapshot("learner.assess", "structured", [model])
    Gateway(lambda m, t: FakeChat(ok()), sleep=lambda s: None, limiter=NoRateLimit()).invoke(
        "learner.assess", MESSAGES, snapshot=snapshot, schema=Answer
    )
    assert float(ModelCall.objects.get().cost) == pytest.approx((10 * 1 + 5 * 4) / 1e6)


class WaitingLimiter:
    def __init__(self, seconds):
        self.seconds = seconds

    def acquire(self, limits):
        return self.seconds


def test_the_wait_for_a_rate_limit_window_is_logged_on_the_call(resolved_model, make_snapshot, FakeChat):
    snapshot = make_snapshot("learner.assess", "structured", [resolved_model("m", provider_rpm=1)])

    Gateway(lambda m, t: FakeChat(ok()), sleep=lambda s: None, limiter=WaitingLimiter(2.5)).invoke(
        "learner.assess", MESSAGES, snapshot=snapshot, schema=Answer
    )

    assert ModelCall.objects.get().rate_limit_wait_ms == 2500


def test_a_call_that_did_not_wait_logs_no_wait(resolved_model, make_snapshot, FakeChat):
    snapshot = make_snapshot("learner.assess", "structured", [resolved_model("m")])

    Gateway(lambda m, t: FakeChat(ok()), sleep=lambda s: None, limiter=NoRateLimit()).invoke(
        "learner.assess", MESSAGES, snapshot=snapshot, schema=Answer
    )

    assert ModelCall.objects.get().rate_limit_wait_ms == 0

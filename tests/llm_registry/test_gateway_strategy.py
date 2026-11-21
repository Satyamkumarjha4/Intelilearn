"""Unit under test: how `llm_registry.gateway.Gateway` uses a layer's settings: strict structured output, its own
timeout, and the circuit breaker.

Why: the strategy (docs/to_be_developed/model-strategy.md 3.2, 3.5) asks Groq for strict JSON (the best-effort default
failed 9 of 14 `learner.assess` calls), gives each layer its own timeout (a Groq layer 3 s, a Gemini 3.6 Flash layer
60 s) and skips a provider that has just refused its key or balance.

Use cases:
- a strict layer on a provider that supports it asks for strict output, when the schema can be sent strictly
- a strict layer whose schema cannot be sent strictly (an optional field) falls back to best effort instead of failing
- a provider that does not take a strict flag is never sent one; best effort sends none; "off" asks for plain JSON mode
- a layer's own timeout is used, else the node's
- the result carries the id of the call that answered (the one a refusing validator keeps the output on), and that is
  the answering layer's row, not an earlier failed one
- three refusals (401) from a provider open the breaker: its layers are then skipped without a call, the next layer
  answers, and a later success on another provider is unaffected
"""

import pytest
from pydantic import BaseModel, Field

from llm_registry.breaker import ProviderBreaker
from llm_registry.gateway import AllModelsFailed, Gateway
from llm_registry.models import ModelCall

pytestmark = pytest.mark.django_db


class Answer(BaseModel):
    value: int


class Loose(BaseModel):
    value: int
    note: str = Field(default="")


class NoLimit:
    def acquire(self, buckets):
        return 0.0


class Unauthorized(Exception):
    status_code = 401


def ok_reply(AIMessage):
    return {"raw": AIMessage(content="", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}),
            "parsed": Answer(value=1), "parsing_error": None}  # fmt: skip


@pytest.fixture
def reply():
    from langchain_core.messages import AIMessage

    return lambda: ok_reply(AIMessage)


def run(chat, model, make_snapshot, schema=Answer, **gateway_kwargs):
    snapshot = make_snapshot("learner.assess", "structured", [model])
    gateway = Gateway(lambda m, timeout: chat, sleep=lambda s: None, limiter=NoLimit(), **gateway_kwargs)
    return gateway.invoke("learner.assess", [("human", "hi")], snapshot=snapshot, schema=schema)


class TestStrictOutput:
    def test_a_strict_layer_asks_for_strict_output(self, resolved_model, make_snapshot, FakeChat, reply):
        chat = FakeChat(reply())

        run(chat, resolved_model("m", provider_kind="groq", structured_mode="strict"), make_snapshot)

        assert chat.structured_kwargs == {"strict": True}

    def test_a_schema_that_cannot_be_sent_strictly_falls_back_to_best_effort(
        self, resolved_model, make_snapshot, FakeChat, reply
    ):
        chat = FakeChat(reply())

        run(chat, resolved_model("m", provider_kind="groq", structured_mode="strict"), make_snapshot, schema=Loose)

        assert chat.structured_kwargs == {}

    @pytest.mark.parametrize("kind", ["google_genai", "anthropic", "openai_compatible"])
    def test_a_provider_that_takes_no_strict_flag_is_not_sent_one(
        self, resolved_model, make_snapshot, FakeChat, reply, kind
    ):
        chat = FakeChat(reply())

        run(chat, resolved_model("m", provider_kind=kind, structured_mode="strict"), make_snapshot)

        assert chat.structured_kwargs == {}

    def test_best_effort_sends_no_flag_and_off_asks_for_plain_json_mode(
        self, resolved_model, make_snapshot, FakeChat, reply
    ):
        best, off = FakeChat(reply()), FakeChat(reply())

        run(best, resolved_model("m", provider_kind="groq", structured_mode="best_effort"), make_snapshot)
        run(off, resolved_model("m", provider_kind="groq", structured_mode="off"), make_snapshot)

        assert best.structured == (Answer, "json_schema", True) and best.structured_kwargs == {}
        assert off.structured == (Answer, "json_mode", True)


class TestResultCall:
    def test_the_result_names_the_call_that_answered(self, resolved_model, make_snapshot, FakeChat, reply):
        first = resolved_model("a", max_retries=0)
        second = resolved_model("b", max_retries=0)
        snapshot = make_snapshot("learner.assess", "structured", [first, second])
        chats = {"a": FakeChat(Unauthorized("no")), "b": FakeChat(reply())}
        gateway = Gateway(lambda m, t: chats[m.model_name], sleep=lambda s: None, limiter=NoLimit())

        result = gateway.invoke("learner.assess", [("human", "hi")], snapshot=snapshot, schema=Answer)

        answered = ModelCall.objects.get(model_name="b", status=ModelCall.Status.OK)
        assert result.call_id == answered.id
        assert ModelCall.objects.count() == 2


class TestTimeout:
    def test_a_layers_own_timeout_is_used_else_the_nodes(self, resolved_model, make_snapshot, FakeChat, reply):
        seen = []
        for own in (7, None):
            snapshot = make_snapshot("learner.assess", "structured", [resolved_model("m", timeout_s=own)])  # node: 30
            gateway = Gateway(lambda m, timeout: seen.append(timeout) or FakeChat(reply()), sleep=lambda s: None,
                              limiter=NoLimit())  # fmt: skip
            gateway.invoke("learner.assess", [("human", "hi")], snapshot=snapshot, schema=Answer)

        assert seen == [7, 30]


class TestBreaker:
    @pytest.fixture
    def breaker(self):
        class Cache(dict):
            def get(self, key, default=None):
                return dict.get(self, key, default)

            def set(self, key, value, timeout=None):
                self[key] = value

            def delete(self, key):
                self.pop(key, None)

        return ProviderBreaker(cache=Cache(), failures=3, cooldown_s=300)

    def test_three_refusals_skip_the_provider_and_the_next_layer_answers(
        self, resolved_model, make_snapshot, FakeChat, reply, breaker
    ):
        refused = resolved_model("a", provider_key="openai", max_retries=0)
        backup = resolved_model("b", provider_key="groq", max_retries=0)
        snapshot = make_snapshot("learner.assess", "structured", [refused, backup])
        a = FakeChat(Unauthorized("no"), Unauthorized("no"), Unauthorized("no"))
        b = FakeChat(reply(), reply(), reply(), reply())
        gateway = Gateway(lambda m, t: {"a": a, "b": b}[m.model_name], sleep=lambda s: None, limiter=NoLimit(),
                          breaker=breaker)  # fmt: skip

        for _ in range(4):
            result = gateway.invoke("learner.assess", [("human", "hi")], snapshot=snapshot, schema=Answer)

        assert result.model.model_name == "b"
        assert len(a.calls) == 3  # the fourth call never reached the refused provider
        assert ModelCall.objects.filter(model_name="a").count() == 3

    def test_when_every_layer_is_skipped_the_error_says_why(self, resolved_model, make_snapshot, FakeChat, breaker):
        for _ in range(3):
            breaker.record_failure("openai", Unauthorized("no"))
        snapshot = make_snapshot("learner.assess", "structured", [resolved_model("a", provider_key="openai")])
        gateway = Gateway(lambda m, t: FakeChat(), sleep=lambda s: None, limiter=NoLimit(), breaker=breaker)

        with pytest.raises(AllModelsFailed, match="skipped"):
            gateway.invoke("learner.assess", [("human", "hi")], snapshot=snapshot, schema=Answer)

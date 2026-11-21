"""Unit under test: `llm_registry.recorder.ModelCallRecorder`, which writes one ModelCall row per gateway attempt.

Why: the call log is how failing models, fallback rates and cost are found. It must mask secrets in errors, and it must
never break a generation run if the write fails.

Use cases:
- records status, tokens (including reasoning tokens), tool calls and cost
- keeps cached input tokens and cache-write tokens, and the thinking tokens apart from the output
- prices a call with the `ModelPrice` row in force on the day of the call, cached input at its own price, and keeps
  the figure as `cost_usd` (and as `cost`, for the readers that have not moved)
- bills an attempt whose reply did not match the schema (the tokens were spent), and has no cost for an error that
  returned no reply
- masks secrets and truncates long errors
- has no cost when the model has no prices or usage is missing
- keeps how long the call waited for a rate-limit window (none by default)
- keeps the quick quiz a call was for, next to the lesson (either may be absent), so a quiz's cost can be told
- a failing write is logged, not raised
- the call's id is returned, so what a validator refuses can be kept on it; a failed write returns none
"""

import pytest
from langchain_core.messages import AIMessage

from llm_registry.models import ModelCall
from llm_registry.recorder import ModelCallRecorder
from llm_registry.redaction import Redactor

pytestmark = pytest.mark.django_db


def record(recorder, model, **fields):
    defaults = dict(node_key="learner.assess", lesson_id=None, run_id=None, model=model, fallback_index=0, attempt=1,
                    status=ModelCall.Status.OK, latency_ms=12)  # fmt: skip
    recorder.record(**{**defaults, **fields})


def test_records_tokens_tool_calls_and_cost(resolved_model):
    model = resolved_model("m", input_cost_per_mtok=1.0, output_cost_per_mtok=4.0)
    usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "output_token_details": {"reasoning": 3}}
    message = AIMessage(content="", usage_metadata=usage, tool_calls=[{"name": "t", "args": {}, "id": "1"}])

    record(ModelCallRecorder(), model, message=message)

    call = ModelCall.objects.get()
    assert (call.input_tokens, call.output_tokens, call.reasoning_tokens, call.tool_calls) == (10, 5, 3, 1)
    assert float(call.cost) == pytest.approx((10 * 1 + 5 * 4) / 1e6)


def test_masks_secrets_and_truncates_errors(resolved_model):
    redactor = Redactor(environ={"GEMINI_API_KEY": "secret-value-123"})

    record(ModelCallRecorder(redactor), resolved_model("m"), status=ModelCall.Status.FATAL_ERROR,
           error="bad key secret-value-123 " + "x" * 5000)  # fmt: skip

    error = ModelCall.objects.get().error
    assert "secret-value-123" not in error and len(error) == ModelCallRecorder.MAX_ERROR_CHARS


def test_no_cost_without_prices_or_usage(resolved_model):
    usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    record(ModelCallRecorder(), resolved_model("m"), message=AIMessage(content="", usage_metadata=usage))
    record(ModelCallRecorder(), resolved_model("m", input_cost_per_mtok=1.0), message=AIMessage(content=""))

    assert [c.cost for c in ModelCall.objects.order_by("created_at")] == [None, None]
    assert [c.cost_usd for c in ModelCall.objects.order_by("created_at")] == [None, None]


def test_keeps_the_rate_limit_wait(resolved_model):
    record(ModelCallRecorder(), resolved_model("m"), rate_limit_wait_ms=1800)
    record(ModelCallRecorder(), resolved_model("m"))

    assert sorted(ModelCall.objects.values_list("rate_limit_wait_ms", flat=True)) == [0, 1800]


def test_keeps_the_quiz_a_call_was_for(resolved_model):
    quiz = "6f1c1b0e-6d7e-4a43-9d38-0c5c3d2b9a11"
    record(ModelCallRecorder(), resolved_model("m"), quiz_id=quiz)
    record(ModelCallRecorder(), resolved_model("m"))

    assert sorted(str(q) for q in ModelCall.objects.values_list("quiz_id", flat=True) if q) == [quiz]
    assert ModelCall.objects.filter(quiz_id__isnull=True).count() == 1


def test_a_failing_write_is_logged_not_raised(resolved_model, monkeypatch, caplog):
    def broken(**kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(ModelCall.objects, "create", broken)

    record(ModelCallRecorder(), resolved_model("m"))

    assert "could not record model call" in caplog.text


class TestCostWithPriceRows:
    @pytest.fixture
    def priced(self, gemini):
        from datetime import date

        from llm_registry.models import LLMModel, ModelPrice

        model = LLMModel.objects.create(provider=gemini, name="gemini-3.6-flash")
        common = {"model": model, "source_url": "https://example.com/p", "checked_on": date(2026, 11, 15)}
        ModelPrice.objects.create(input_per_mtok=1, output_per_mtok=4, cached_input_per_mtok="0.1",
                                  valid_until=date(2026, 12, 31), **common)  # fmt: skip
        ModelPrice.objects.create(input_per_mtok=2, output_per_mtok=8, cached_input_per_mtok="0.2",
                                  valid_from=date(2027, 1, 1), **common)  # fmt: skip
        return model

    def message(self, **details):
        usage = {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500, **details}
        return AIMessage(content="", usage_metadata=usage)

    def test_cached_and_cache_write_tokens_and_thinking_are_kept_apart(self, priced, resolved_model):
        message = self.message(input_token_details={"cache_read": 600, "cache_creation": 100},
                               output_token_details={"reasoning": 200})  # fmt: skip

        record(ModelCallRecorder(), resolved_model("gemini-3.6-flash", provider_key="gemini"), message=message)

        call = ModelCall.objects.get()
        assert (call.input_tokens, call.output_tokens) == (1000, 500)
        assert (call.cached_input_tokens, call.cache_write_tokens, call.reasoning_tokens) == (600, 100, 200)

    def test_the_price_row_of_the_day_of_the_call_is_used_and_cached_input_is_cheaper(self, priced, resolved_model):
        from datetime import date

        message = self.message(input_token_details={"cache_read": 600})
        model = resolved_model("gemini-3.6-flash", provider_key="gemini")

        record(ModelCallRecorder(today=lambda: date(2026, 12, 31)), model, message=message)
        record(ModelCallRecorder(today=lambda: date(2027, 1, 1)), model, message=message)

        promo, after = ModelCall.objects.order_by("created_at")
        assert float(promo.cost_usd) == pytest.approx((400 * 1 + 600 * 0.1 + 500 * 4) / 1e6)
        assert float(after.cost_usd) == pytest.approx((400 * 2 + 600 * 0.2 + 500 * 8) / 1e6)
        assert promo.cost == promo.cost_usd and after.cost == after.cost_usd

    def test_an_attempt_whose_reply_did_not_match_the_schema_is_billed(self, priced, resolved_model):
        record(ModelCallRecorder(), resolved_model("gemini-3.6-flash", provider_key="gemini"),
               status=ModelCall.Status.INVALID_OUTPUT, message=self.message())  # fmt: skip

        assert ModelCall.objects.get().cost_usd is not None

    def test_an_error_that_returned_no_reply_has_no_cost(self, priced, resolved_model):
        record(ModelCallRecorder(), resolved_model("gemini-3.6-flash", provider_key="gemini"),
               status=ModelCall.Status.RETRYABLE_ERROR)  # fmt: skip

        assert ModelCall.objects.get().cost_usd is None


def test_returns_the_id_of_the_row_it_wrote(resolved_model):
    call_id = ModelCallRecorder().record(
        node_key="learner.assess", lesson_id=None, run_id=None, model=resolved_model("m"), fallback_index=0,
        attempt=1, status=ModelCall.Status.OK, latency_ms=12)  # fmt: skip

    assert call_id == ModelCall.objects.get().id


def test_returns_no_id_when_the_write_fails(resolved_model, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(ModelCall.objects, "create", broken)

    call_id = ModelCallRecorder().record(
        node_key="learner.assess", lesson_id=None, run_id=None, model=resolved_model("m"), fallback_index=0,
        attempt=1, status=ModelCall.Status.OK, latency_ms=12)  # fmt: skip

    assert call_id is None

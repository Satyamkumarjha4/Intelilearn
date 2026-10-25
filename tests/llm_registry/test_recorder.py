"""Unit under test: `llm_registry.recorder.ModelCallRecorder`, which writes one ModelCall row per gateway attempt.

Why: the call log is how failing models, fallback rates and cost are found. It must mask secrets in errors, and it must
never break a generation run if the write fails.

Use cases:
- records status, tokens (including reasoning tokens), tool calls and cost
- masks secrets and truncates long errors
- has no cost when the model has no prices or usage is missing
- keeps how long the call waited for a rate-limit window (none by default)
- a failing write is logged, not raised
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
    assert ModelCallRecorder.cost(resolved_model("m"), 10, 5) is None
    assert ModelCallRecorder.cost(resolved_model("m", input_cost_per_mtok=1.0), None, 5) is None


def test_keeps_the_rate_limit_wait(resolved_model):
    record(ModelCallRecorder(), resolved_model("m"), rate_limit_wait_ms=1800)
    record(ModelCallRecorder(), resolved_model("m"))

    assert sorted(ModelCall.objects.values_list("rate_limit_wait_ms", flat=True)) == [0, 1800]


def test_a_failing_write_is_logged_not_raised(resolved_model, monkeypatch, caplog):
    def broken(**kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(ModelCall.objects, "create", broken)

    record(ModelCallRecorder(), resolved_model("m"))

    assert "could not record model call" in caplog.text

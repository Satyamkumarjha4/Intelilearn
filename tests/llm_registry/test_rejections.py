"""Unit under test: `llm_registry.rejections.RejectedOutputs`, which keeps what a model wrote when a validator refused
it, on the `ModelCall` of the attempt that wrote it.

Why: "options must all be different" told us a quiz was refused, not what the model had written, so the first live run
could not say whether the model or the validator was at fault; the answer took two days of re-running with a spy. The
refused output is the evidence. It holds what a lesson was about (a learner's topic and context), so it is kept for
staff only, for a short time, and goes with the lesson when an account is erased; and a failed write must never fail a
lesson.

Use cases:
- the output a validator refused and the problems it gave are stored on the call that wrote it, and on no other call
- the output is stored as readable JSON (a Hindi question stays Hindi), and a text output as it is
- secrets in the output are masked, and an output over the limit is cut and says so
- no call id (a model that was not recorded) or an id that is not a call stores nothing and raises nothing
- a call that was recorded without a refusal has none
- `forget_before` empties the stored output and problems of calls older than the cutoff, keeps the calls themselves
  (status, tokens and cost are the usage log), leaves newer ones, counts only what it emptied, and a second run empties
  nothing
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from llm_registry.models import ModelCall
from llm_registry.redaction import Redactor
from llm_registry.rejections import RejectedOutputs

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 17, 3, 0, tzinfo=UTC)


def make_call(**fields) -> ModelCall:
    defaults = dict(node_key="diagnostic.generate", provider_key="groq", model_name="m", attempt=1, fallback_index=0,
                    status=ModelCall.Status.OK, latency_ms=5, cost_usd="0.001000")  # fmt: skip
    return ModelCall.objects.create(**{**defaults, **fields})


def test_stores_the_output_and_the_problems_on_that_call_only():
    call, other = make_call(), make_call()

    stored = RejectedOutputs().record(call.id, {"diagnostic": [{"id": "q1", "options": ["a", "a"]}]},
                                      ["Question q1: options must all be different.", "Question q2: bad."])  # fmt: skip

    call.refresh_from_db(), other.refresh_from_db()
    assert stored is True
    assert json.loads(call.rejected_output) == {"diagnostic": [{"id": "q1", "options": ["a", "a"]}]}
    assert call.rejection == "Question q1: options must all be different.\nQuestion q2: bad."
    assert (other.rejected_output, other.rejection) == ("", "")


def test_keeps_readable_text_and_a_text_output_as_it_is():
    hindi, text = make_call(), make_call()

    RejectedOutputs().record(hindi.id, {"question": "सबसे बड़ी संख्या कौन सी है?"}, ["p"])
    RejectedOutputs().record(text.id, "plain words", ["p"])

    hindi.refresh_from_db(), text.refresh_from_db()
    assert "सबसे बड़ी संख्या कौन सी है?" in hindi.rejected_output and "\\u" not in hindi.rejected_output
    assert text.rejected_output == "plain words"


def test_masks_secrets_and_cuts_a_long_output():
    leaky, long = make_call(), make_call()
    sink = RejectedOutputs(redactor=Redactor(environ={"GEMINI_API_KEY": "secret-value-123"}))

    sink.record(leaky.id, "my key is secret-value-123", ["p"])
    sink.record(long.id, "x" * (RejectedOutputs.MAX_CHARS + 500), ["p"])

    leaky.refresh_from_db(), long.refresh_from_db()
    assert "secret-value-123" not in leaky.rejected_output
    assert len(long.rejected_output) <= RejectedOutputs.MAX_CHARS + 80
    assert long.rejected_output.endswith("… (cut)")


@pytest.mark.parametrize("call_id", [None, 999_999])
def test_without_a_recorded_call_it_stores_nothing_and_raises_nothing(call_id):
    make_call()

    assert RejectedOutputs().record(call_id, {"a": 1}, ["p"]) is False
    assert ModelCall.objects.exclude(rejected_output="").count() == 0


def test_a_call_with_no_refusal_has_no_stored_output():
    call = make_call()

    assert (call.rejected_output, call.rejection) == ("", "")


def test_forget_before_empties_old_outputs_and_keeps_the_calls():
    old = make_call()
    recent = make_call()
    never = make_call()
    RejectedOutputs().record(old.id, "old output", ["old problem"])
    RejectedOutputs().record(recent.id, "new output", ["new problem"])
    ModelCall.objects.filter(pk=old.pk).update(created_at=NOW - timedelta(days=15))
    ModelCall.objects.filter(pk=recent.pk).update(created_at=NOW - timedelta(days=13))
    ModelCall.objects.filter(pk=never.pk).update(created_at=NOW - timedelta(days=40))

    emptied = RejectedOutputs().forget_before(NOW - timedelta(days=14))

    old.refresh_from_db(), recent.refresh_from_db()
    assert emptied == 1
    assert (old.rejected_output, old.rejection) == ("", "")
    assert (old.status, str(old.cost_usd)) == ("ok", "0.001000")
    assert recent.rejected_output == "new output" and recent.rejection == "new problem"
    assert RejectedOutputs().forget_before(NOW - timedelta(days=14)) == 0

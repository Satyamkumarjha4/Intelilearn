"""Unit under test: `console.outcomes.CallOutcomes` (what ok, retried, failed and fallback mean for a ModelCall row)
and `PercentileCont` (Postgres `percentile_cont`).

Why: the overview, the usage page and the CSV all say how many calls worked, needed a retry or failed. If each counted
in its own way the numbers on two pages would disagree, and a stacked bar would not add up to the calls made.

Use cases:
- every call is exactly one of ok (worked first time), retried (worked on a later attempt) or failed (any other status)
- a fallback is any attempt on a model after the first in the chain, whatever came of it; it overlaps the three outcomes
- a retry attempt is any attempt after the first on one model, whatever came of it
- the counts aggregate in one query and add up to the total
- an outcome name filters a queryset; an unknown name is refused
- naming a single row in Python (for the CSV) agrees with the SQL conditions, for every status and attempt
- PercentileCont interpolates like Postgres does (median of 1,2,3,4 is 2.5) and honours a filter
"""

import pytest
from django.db.models import Q

from console.outcomes import CallOutcomes, PercentileCont
from llm_registry.models import ModelCall

pytestmark = pytest.mark.django_db

OK, RETRYABLE, FATAL, INVALID = (
    ModelCall.Status.OK,
    ModelCall.Status.RETRYABLE_ERROR,
    ModelCall.Status.FATAL_ERROR,
    ModelCall.Status.INVALID_OUTPUT,
)


@pytest.fixture
def calls(make_call):
    return {
        "ok": make_call(),
        "retried": make_call(attempt=2),
        "failed_retryable": make_call(status=RETRYABLE, attempt=1),
        "failed_after_retry": make_call(status=FATAL, attempt=3),
        "invalid": make_call(status=INVALID),
        "fallback_ok": make_call(fallback_index=1),
    }


def names(queryset, calls):
    return sorted(name for name, call in calls.items() if call.pk in set(queryset.values_list("pk", flat=True)))


def test_every_call_is_exactly_one_outcome(calls):
    ok = ModelCall.objects.filter(CallOutcomes.condition("ok"))
    retried = ModelCall.objects.filter(CallOutcomes.condition("retried"))
    failed = ModelCall.objects.filter(CallOutcomes.condition("failed"))

    assert names(ok, calls) == ["fallback_ok", "ok"]
    assert names(retried, calls) == ["retried"]
    assert names(failed, calls) == ["failed_after_retry", "failed_retryable", "invalid"]


def test_a_fallback_is_any_attempt_after_the_first_model(calls):
    assert names(ModelCall.objects.filter(CallOutcomes.FALLBACK), calls) == ["fallback_ok"]


def test_a_retry_attempt_is_any_attempt_after_the_first_on_a_model(calls):
    assert names(ModelCall.objects.filter(CallOutcomes.RETRY_ATTEMPT), calls) == ["failed_after_retry", "retried"]


def test_the_counts_add_up_to_the_calls_made(calls, django_assert_num_queries):
    with django_assert_num_queries(1):
        counts = ModelCall.objects.aggregate(total=CallOutcomes.total(), **CallOutcomes.counts())

    assert counts == {"total": 6, "ok": 2, "retried": 1, "failed": 3, "fallbacks": 1, "retries": 2}
    assert counts["ok"] + counts["retried"] + counts["failed"] == counts["total"]


@pytest.mark.parametrize("status", ModelCall.Status.values)
@pytest.mark.parametrize("attempt", [1, 2, 3])
def test_naming_one_row_agrees_with_the_sql_conditions(make_call, status, attempt):
    call = make_call(status=status, attempt=attempt)

    matching = [name for name in CallOutcomes.NAMES if ModelCall.objects.filter(CallOutcomes.condition(name)).exists()]

    assert matching == [CallOutcomes.name_of(call.status, call.attempt)]


def test_an_unknown_outcome_is_refused():
    with pytest.raises(ValueError, match="outcome"):
        CallOutcomes.condition("slow")


def test_percentile_cont_interpolates_and_honours_a_filter(make_call):
    for ms in (1000, 2000, 3000, 4000):
        make_call(latency_ms=ms)
    make_call(latency_ms=90_000, status=FATAL)

    result = ModelCall.objects.aggregate(
        median=PercentileCont("latency_ms", 0.5, filter=Q(status=OK)),
        p95=PercentileCont("latency_ms", 0.95, filter=Q(status=OK)),
        nothing=PercentileCont("latency_ms", 0.5, filter=Q(status="no-such-status")),
    )

    assert result["median"] == pytest.approx(2500)
    assert result["p95"] == pytest.approx(3850)
    assert result["nothing"] is None

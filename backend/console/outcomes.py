"""What the console means by a call that worked, was retried, failed or fell back, in one place (Specification).

A `ModelCall` row is one *attempt* (llm_registry/gateway.py): a retry on the same model, or the next model after a
failure, is another row. Each row is exactly one of three outcomes, so counts add up to the calls made:

  ok       status ok on the first attempt on its model
  retried  status ok, but only on a later attempt (attempt > 1): the model failed and the retry worked
  failed   any other status (retryable, fatal or invalid output)

Two more counts overlap those: a *fallback* is an attempt on a model after the first in the node's chain
(fallback_index > 0), whatever came of it; a *retry attempt* is any attempt after the first on one model (attempt > 1).
An invalid-output repair does not count as a retry in the log (the gateway does not advance `attempt` for it).
"""

from django.db.models import Aggregate, Count, FloatField, Q

from llm_registry.models import ModelCall


class CallOutcomes:
    NAMES = ("ok", "retried", "failed")

    _OK = Q(status=ModelCall.Status.OK)
    CONDITIONS = {
        "ok": _OK & Q(attempt=1),
        "retried": _OK & Q(attempt__gt=1),
        "failed": ~_OK,
    }
    FALLBACK = Q(fallback_index__gt=0)
    RETRY_ATTEMPT = Q(attempt__gt=1)

    @classmethod
    def condition(cls, name: str) -> Q:
        try:
            return cls.CONDITIONS[name]
        except KeyError:
            raise ValueError(f"Unknown outcome {name!r}; choose one of: {', '.join(cls.NAMES)}") from None

    @staticmethod
    def name_of(status: str, attempt: int) -> str:
        """The outcome of one row, for code that has the row in hand (the same rule as `CONDITIONS`)."""
        if status != ModelCall.Status.OK:
            return "failed"
        return "ok" if attempt == 1 else "retried"

    @staticmethod
    def total() -> Count:
        return Count("id")

    @classmethod
    def counts(cls) -> dict[str, Count]:
        """Aggregates for `.aggregate()` or `.annotate()`: how many calls had each outcome, and the overlapping two."""
        return {
            **{name: Count("id", filter=cls.CONDITIONS[name]) for name in cls.NAMES},
            "fallbacks": Count("id", filter=cls.FALLBACK),
            "retries": Count("id", filter=cls.RETRY_ATTEMPT),
        }


class PercentileCont(Aggregate):
    """Postgres `percentile_cont(fraction) WITHIN GROUP (ORDER BY expression)`: the interpolated percentile, in the
    expression's unit, or NULL when there are no rows. Takes `filter=` like any aggregate."""

    function = "percentile_cont"
    template = "%(function)s(%(fraction)s) WITHIN GROUP (ORDER BY %(expressions)s)"
    allow_distinct = False

    def __init__(self, expression, fraction: float, **extra):
        # The fraction goes into the SQL text, not a parameter (the syntax takes no placeholder there): float() keeps
        # it a number whatever the caller passes.
        super().__init__(expression, output_field=FloatField(), fraction=float(fraction), **extra)

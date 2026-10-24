"""What the model calls cost and how long they take, per node and per model: the admin dashboard's numbers.

`UsageReport` reads the `ModelCall` log. Every attempt is a row (a retry or a fallback is another row), so `calls`
counts attempts, `success_rate` is the share that gave a usable answer, and `fallbacks` counts the attempts made on a
fallback model. Latency is of the attempts that succeeded: an error that fails fast says nothing about speed.
"""

import math
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q, QuerySet, Sum
from django.utils import timezone

from .models import ModelCall


@dataclass(frozen=True)
class Usage:
    label: str
    calls: int
    succeeded: int
    fallbacks: int
    input_tokens: int
    output_tokens: int
    cost: Decimal
    avg_ms: int
    p95_ms: int

    @property
    def success_rate(self) -> int:
        return round(100 * self.succeeded / self.calls) if self.calls else 0

    @property
    def failed(self) -> int:
        return self.calls - self.succeeded


class UsageReport:
    #: the windows the dashboard offers, in days (None: everything that was logged)
    WINDOWS = {"1": 1, "7": 7, "30": 30, "all": None}

    def __init__(self, calls: QuerySet[ModelCall] | None = None, now=None):
        self.calls = ModelCall.objects.all() if calls is None else calls
        self.now = now or timezone.now()

    def within(self, window: str) -> "UsageReport":
        days = self.WINDOWS.get(window, self.WINDOWS["7"])
        if days is None:
            return self
        return UsageReport(self.calls.filter(created_at__gte=self.now - timedelta(days=days)), self.now)

    def per_node(self) -> list[Usage]:
        return self._grouped("node_key")

    def per_model(self) -> list[Usage]:
        return self._grouped("provider_key", "model_name")

    def total(self) -> Usage:
        return self._usage("All calls", self.calls)

    def _grouped(self, *fields: str) -> list[Usage]:
        """One `Usage` per distinct value of `fields`, the costliest first."""
        usages = [
            self._usage("/".join(key), self.calls.filter(**dict(zip(fields, key, strict=True))))
            for key in self.calls.order_by(*fields).values_list(*fields).distinct()
        ]
        return sorted(usages, key=lambda u: (-u.cost, -u.calls, u.label))

    def _usage(self, label: str, calls: QuerySet[ModelCall]) -> Usage:
        totals = calls.aggregate(
            n=Count("id"),
            ok=Count("id", filter=Q(status=ModelCall.Status.OK)),
            fallback=Count("id", filter=Q(fallback_index__gt=0)),
            tokens_in=Sum("input_tokens"),
            tokens_out=Sum("output_tokens"),
            cost=Sum("cost"),
            avg=Avg("latency_ms", filter=Q(status=ModelCall.Status.OK)),
        )
        latencies = sorted(calls.filter(status=ModelCall.Status.OK).values_list("latency_ms", flat=True))
        return Usage(
            label=label,
            calls=totals["n"],
            succeeded=totals["ok"],
            fallbacks=totals["fallback"],
            input_tokens=totals["tokens_in"] or 0,
            output_tokens=totals["tokens_out"] or 0,
            cost=totals["cost"] or Decimal(0),
            avg_ms=round(totals["avg"] or 0),
            p95_ms=self._percentile(latencies, 95),
        )

    @staticmethod
    def _percentile(sorted_values: list[int], percent: int) -> int:
        """Nearest-rank percentile of an already sorted list (0 for an empty one)."""
        if not sorted_values:
            return 0
        rank = math.ceil(percent / 100 * len(sorted_values))
        return sorted_values[max(rank, 1) - 1]

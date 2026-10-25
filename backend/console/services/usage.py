"""The usage page: what the model calls cost and how long they take, filtered, and the same calls as a CSV.

`UsageFilters` says which calls (a range plus an optional provider, model, step and outcome) and `UsageReport` totals
them three ways: overall, per model and per step. Call times are of the calls that *worked* (an error that fails fast
says nothing about speed), as percentiles taken by Postgres (`percentile_cont`, interpolated). What ok, retried, failed
and fallback mean is in `console/outcomes.py`. `UsageCsv` writes the raw rows.
"""

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, QuerySet, Sum

from console.outcomes import CallOutcomes, PercentileCont
from console.periods import Period
from llm_registry.models import ModelCall

from .overview import money


@dataclass(frozen=True)
class UsageFilters:
    period: Period
    provider: str = ""
    model: str = ""
    node: str = ""
    outcome: str = ""

    @classmethod
    def of(cls, period: Period, provider="", model="", node="", outcome="") -> "UsageFilters":
        return cls(period, provider or "", model or "", node or "", outcome or "")

    def calls(self) -> QuerySet[ModelCall]:
        calls = ModelCall.objects.filter(created_at__gte=self.period.start, created_at__lte=self.period.end)
        for field, value in (("provider_key", self.provider), ("model_name", self.model), ("node_key", self.node)):
            if value:
                calls = calls.filter(**{field: value})
        return calls.filter(CallOutcomes.condition(self.outcome)) if self.outcome else calls


class UsageReport:
    WORKED = Q(status=ModelCall.Status.OK)

    def build(self, filters: UsageFilters) -> dict:
        calls = filters.calls()
        return {
            "range": filters.period.key,
            "period": {"start": filters.period.start, "end": filters.period.end},
            "kpis": self._kpis(calls),
            "by_model": self._by_model(calls),
            "by_node": self._by_node(calls),
        }

    def _kpis(self, calls: QuerySet[ModelCall]) -> dict:
        totals = calls.aggregate(
            calls=Count("id"),
            tokens_in=Sum("input_tokens"),
            tokens_out=Sum("output_tokens"),
            spend=Sum("cost"),
            median=self._percentile(0.5),
            p95=self._percentile(0.95),
        )
        return {
            "calls": totals["calls"],
            "tokens_in": totals["tokens_in"] or 0,
            "tokens_out": totals["tokens_out"] or 0,
            "spend": str(money(totals["spend"])),
            "median_latency_s": self._seconds(totals["median"]),
            "p95_latency_s": self._seconds(totals["p95"]),
        }

    def _by_model(self, calls: QuerySet[ModelCall]) -> list[dict]:
        rows = (
            calls.values("provider_key", "model_name")
            .annotate(
                n=Count("id"),
                spend=Sum("cost"),
                median=self._percentile(0.5),
                p95=self._percentile(0.95),
                **CallOutcomes.counts(),
            )
            .order_by("-n", "provider_key", "model_name")
        )
        return [
            {
                "model": row["model_name"],
                "provider": row["provider_key"],
                "median_s": self._seconds(row["median"]),
                "p95_s": self._seconds(row["p95"]),
                "ok": row["ok"],
                "retried": row["retried"],
                "failed": row["failed"],
                "calls": row["n"],
                "spend": str(money(row["spend"])),
            }
            for row in rows
        ]

    def _by_node(self, calls: QuerySet[ModelCall]) -> list[dict]:
        rows = (
            calls.values("node_key")
            .annotate(
                n=Count("id"),
                tokens_in=Sum("input_tokens"),
                tokens_out=Sum("output_tokens"),
                spend=Sum("cost"),
                p95=self._percentile(0.95),
                **CallOutcomes.counts(),
            )
            .order_by("-n", "node_key")
        )
        return [
            {
                "node": row["node_key"],
                "calls": row["n"],
                "ok_pct": round(100 * (row["ok"] + row["retried"]) / row["n"], 1),
                "retries": row["retries"],
                "fallbacks": row["fallbacks"],
                "tokens_k": round(((row["tokens_in"] or 0) + (row["tokens_out"] or 0)) / 1000, 1),
                "spend": str(money(row["spend"])),
                "p95_s": self._seconds(row["p95"]),
            }
            for row in rows
        ]

    def _percentile(self, fraction: float) -> PercentileCont:
        return PercentileCont("latency_ms", fraction, filter=self.WORKED)

    @staticmethod
    def _seconds(milliseconds: float | None) -> float | None:
        return None if milliseconds is None else round(milliseconds / 1000, 3)


class Echo:
    """A file-like whose `write` returns what it is given, so `csv.writer` yields rows instead of storing them."""

    def write(self, value: str) -> str:
        return value


class UsageCsv:
    """The filtered calls, one row each, oldest first, as a stream (the export can be far bigger than a page)."""

    COLUMNS = [
        "created_at", "node", "provider", "model", "attempt", "fallback_index", "status", "outcome", "latency_ms",
        "rate_limit_wait_ms", "tokens_in", "tokens_out", "reasoning_tokens", "tool_calls", "cost", "lesson_id",
        "run_id", "error",
    ]  # fmt: skip
    #: a cell starting with one of these is read by a spreadsheet as a formula
    FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")

    def rows(self, filters: UsageFilters) -> Iterator[str]:
        writer = csv.writer(Echo())
        yield writer.writerow(self.COLUMNS)
        for call in filters.calls().order_by("created_at", "id").iterator(chunk_size=2000):
            yield writer.writerow(self._row(call))

    def filename(self, filters: UsageFilters) -> str:
        last_day = (filters.period.end - timedelta(microseconds=1)).date()  # a custom range ends at midnight
        return f"socra-usage-{filters.period.key}-{last_day.isoformat()}.csv"

    def _row(self, call: ModelCall) -> list:
        cost = None if call.cost is None else str(money(Decimal(call.cost)))
        values = [
            call.created_at.isoformat(), call.node_key, call.provider_key, call.model_name, call.attempt,
            call.fallback_index, call.status, CallOutcomes.name_of(call.status, call.attempt), call.latency_ms,
            call.rate_limit_wait_ms, call.input_tokens, call.output_tokens, call.reasoning_tokens, call.tool_calls,
            cost, call.lesson_id, call.run_id, call.error,
        ]  # fmt: skip
        return ["" if value is None else self._defused(value) for value in values]

    def _defused(self, value):
        """Text a spreadsheet would run as a formula gets a leading apostrophe (OWASP's CSV-injection advice)."""
        text = str(value)
        return "'" + text if isinstance(value, str) and text.startswith(self.FORMULA_STARTS) else value

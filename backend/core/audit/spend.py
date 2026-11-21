"""What a live audit has spent on models, against the cap (`LIVE_MAX_COST_USD`).

The throwaway stack's call log (`ModelCall`) is the only record: its database holds nothing but the audit's own calls.
A call the log could not price is counted apart, because an unknown cost is not a zero one.
"""

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Q, Sum

from llm_registry.models import ModelCall


class BadCap(ValueError):
    """LIVE_MAX_COST_USD that is not a number of dollars, 0 or more."""


@dataclass(frozen=True)
class SpendReport:
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    unpriced: int  # calls with no cost: the total may be low by what they cost
    cap: Decimal

    @property
    def over(self) -> bool:
        return self.cost_usd > self.cap


class AuditSpend:
    DEFAULT_CAP = Decimal("2.00")
    ENV = "LIVE_MAX_COST_USD"

    def __init__(self, cap: Decimal):
        self.cap = cap

    @classmethod
    def from_environment(cls) -> "AuditSpend":
        raw = os.environ.get(cls.ENV)
        if raw is None:
            return cls(cls.DEFAULT_CAP)
        try:
            cap = Decimal(raw)
        except InvalidOperation:
            raise BadCap(f"{cls.ENV} must be a number of dollars.") from None
        if not cap.is_finite() or cap < 0:
            raise BadCap(f"{cls.ENV} must be a number of dollars, 0 or more.")
        return cls(cap)

    def report(self) -> SpendReport:
        totals = ModelCall.objects.aggregate(
            calls=Count("id"),
            cost=Sum("cost_usd"),
            input_tokens=Sum("input_tokens"),
            output_tokens=Sum("output_tokens"),
            unpriced=Count("id", filter=Q(cost_usd__isnull=True)),
        )
        return SpendReport(
            calls=totals["calls"],
            input_tokens=totals["input_tokens"] or 0,
            output_tokens=totals["output_tokens"] or 0,
            cost_usd=totals["cost"] or Decimal("0"),
            unpriced=totals["unpriced"],
            cap=self.cap,
        )

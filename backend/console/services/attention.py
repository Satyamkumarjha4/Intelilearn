"""The overview's "needs attention" list: one `AttentionRule` per kind of problem (Strategy).

Each rule reads what it needs and returns zero or more `Attention` items. A new kind of warning is a new rule class
added to `AttentionRules.DEFAULT`; the overview does not change. Every rule runs a fixed number of queries.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Count, Q, Sum

from console.outcomes import CallOutcomes
from console.periods import Period
from lessons.models import Lesson
from lessons.stages import Stage
from llm_registry.models import ModelCall, Provider


@dataclass(frozen=True)
class Attention:
    kind: str
    severity: str  # error, warning or info
    title: str
    detail: str
    link: str  # a console page, which a UI can open


@dataclass(frozen=True)
class AttentionContext:
    period: Period
    now: datetime


class AttentionRule(ABC):
    @abstractmethod
    def evaluate(self, context: AttentionContext) -> list[Attention]:
        """What this rule found (nothing, when all is well)."""


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


class FailedLessonsRule(AttentionRule):
    """Lessons that stopped with an error in the last 24 hours."""

    def evaluate(self, context: AttentionContext) -> list[Attention]:
        failed = Lesson.objects.filter(stage=Stage.FAILED, updated_at__gte=context.now - timedelta(hours=24))
        count = failed.count()
        if not count:
            return []
        latest = failed.order_by("-updated_at").values_list("error", flat=True).first() or "No reason was recorded."
        return [
            Attention(
                "lessons_failed",
                "error",
                f"{plural(count, 'lesson')} failed in the last 24 hours",
                f"Latest: {latest[:160]}",
                "/console/runs?status=failed",
            )
        ]


class FailingModelRule(AttentionRule):
    """A model that fails more than a fifth of its calls, once it has made enough of them to say so."""

    MIN_CALLS = 20
    MAX_FAILURE_RATE = 0.20
    ERROR_RATE = 0.50  # past this it is an error, not a warning

    def evaluate(self, context: AttentionContext) -> list[Attention]:
        in_range = ModelCall.objects.filter(created_at__gte=context.period.start, created_at__lte=context.period.end)
        per_model = in_range.values("provider_key", "model_name").annotate(
            total=Count("id"), failed=Count("id", filter=CallOutcomes.condition("failed"))
        )
        failing = [
            row
            for row in per_model
            if row["total"] >= self.MIN_CALLS and row["failed"] / row["total"] > self.MAX_FAILURE_RATE
        ]
        if not failing:
            return []
        usual = self._usual_problems(in_range, failing)
        return [
            Attention(
                "model_failing",
                "error" if row["failed"] / row["total"] > self.ERROR_RATE else "warning",
                f"{row['model_name']} is failing {round(100 * row['failed'] / row['total'])}% of calls",
                f"Mostly {usual[(row['provider_key'], row['model_name'])].lower()} · "
                f"{row['failed']} of {row['total']} calls failed",
                f"/console/usage?model={row['model_name']}",
            )
            for row in sorted(failing, key=lambda r: -r["failed"] / r["total"])
        ]

    @staticmethod
    def _usual_problems(in_range, failing: list[dict]) -> dict[tuple[str, str], str]:
        """The most common failure status of each failing model, for all of them in one query."""
        labels = dict(ModelCall.Status.choices)
        wanted = Q()
        for row in failing:
            wanted |= Q(provider_key=row["provider_key"], model_name=row["model_name"])
        rows = (
            in_range.filter(wanted, CallOutcomes.condition("failed"))
            .values("provider_key", "model_name", "status")
            .annotate(n=Count("id"))
            .order_by("n")  # ascending, so the most common status is the last one written
        )
        return {(r["provider_key"], r["model_name"]): labels[r["status"]] for r in rows}


class RateLimitWaitRule(AttentionRule):
    """Calls today that stood in line for a provider's requests-per-minute window (or gave up doing so)."""

    def evaluate(self, context: AttentionContext) -> list[Attention]:
        midnight = context.now.replace(hour=0, minute=0, second=0, microsecond=0)
        waited = ModelCall.objects.filter(created_at__gte=midnight, created_at__lte=context.now).filter(
            Q(rate_limit_wait_ms__gt=0) | Q(error__contains="RateLimitWaitExceeded")
        )
        totals = waited.aggregate(calls=Count("id"), wait_ms=Sum("rate_limit_wait_ms"))
        if not totals["calls"]:
            return []
        return [
            Attention(
                "rate_limit_waits",
                "info",
                f"{plural(totals['calls'], 'call')} waited for a rate limit today",
                f"{self._duration((totals['wait_ms'] or 0) / 1000)} spent waiting in total. "
                "Raise the limit on a paid plan, or add a model on another provider.",
                "/console/models",
            )
        ]

    @staticmethod
    def _duration(seconds: float) -> str:
        if seconds < 60:
            return f"{round(seconds)} seconds"
        minutes = round(seconds / 60, 1)
        return f"{minutes:g} minute{'' if minutes == 1 else 's'}"


class MissingKeyRule(AttentionRule):
    """A provider whose models are in use by a step, but whose API key is not set on the server."""

    def evaluate(self, context: AttentionContext) -> list[Attention]:
        in_use = Q(models__bindings__is_enabled=True, models__bindings__node__is_enabled=True)
        providers = (
            Provider.objects.filter(is_enabled=True)
            .filter(in_use)
            .annotate(steps=Count("models__bindings", filter=in_use, distinct=True))
        )
        return [
            Attention(
                "provider_key_missing",
                "error",
                f"{provider.key} has no API key",
                f"Set {provider.api_key_env} on the server. {plural(provider.steps, 'step')} "
                f"{'is' if provider.steps == 1 else 'are'} bound to its models.",
                "/console/models",
            )
            for provider in providers
            if not provider.has_api_key
        ]


class AttentionRules:
    SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
    DEFAULT: tuple[AttentionRule, ...] = (
        FailedLessonsRule(),
        FailingModelRule(),
        RateLimitWaitRule(),
        MissingKeyRule(),
    )

    def __init__(self, rules: Sequence[AttentionRule] | None = None):
        self._rules = tuple(rules) if rules is not None else self.DEFAULT

    def evaluate(self, context: AttentionContext) -> list[Attention]:
        found = [item for rule in self._rules for item in rule.evaluate(context)]
        return sorted(found, key=lambda item: self.SEVERITY_ORDER[item.severity])  # stable: rules keep their order

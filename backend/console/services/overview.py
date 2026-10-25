"""The numbers behind the console's first page. `OverviewReport` (Facade) asks one small collaborator per card, so a
card can change without touching the others, and builds the whole page in a fixed number of queries.
"""

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from console.outcomes import CallOutcomes, PercentileCont
from console.periods import Period, Periods
from lessons.models import Lesson, Quiz
from lessons.stages import Route, Stage
from llm_registry.models import ModelCall

from .attention import AttentionContext, AttentionRules
from .health import ConsoleHealth

MONEY = Decimal("0.000001")  # money is shown to the six places the calls are stored with


def money(amount) -> Decimal:
    return Decimal(amount or 0).quantize(MONEY)


class LessonCounts:
    """Lessons started, finished and failed in the range, and started in the range before it.

    A lesson has no "finished at": it counts as finished or failed in the range where its row last changed to that
    stage, which is when it got there unless something touched it afterwards."""

    def of(self, period: Period) -> dict:
        in_range = Q(created_at__gte=period.start, created_at__lte=period.end)
        before = Q(created_at__gte=period.previous_start, created_at__lt=period.previous_end)
        changed = Q(updated_at__gte=period.start, updated_at__lte=period.end)
        changed_before = Q(updated_at__gte=period.previous_start, updated_at__lt=period.previous_end)
        return Lesson.objects.aggregate(
            started=Count("id", filter=in_range),
            finished=Count("id", filter=changed & Q(stage=Stage.READY)),
            failed=Count("id", filter=changed & Q(stage=Stage.FAILED)),
            previous_started=Count("id", filter=before),
            previous_finished=Count("id", filter=changed_before & Q(stage=Stage.READY)),
        )


class SpendSummary:
    def __init__(self, budget: Decimal | None = None):
        self._budget = budget

    def of(self, period: Period) -> dict:
        in_range = ModelCall.objects.filter(created_at__gte=period.start, created_at__lte=period.end)
        totals = in_range.aggregate(total=Sum("cost"), lessons=Count("lesson_id", distinct=True))
        month_start = timezone.localtime(period.end).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month = ModelCall.objects.filter(created_at__gte=month_start, created_at__lte=period.end).aggregate(
            total=Sum("cost")
        )
        total = money(totals["total"])
        per_lesson = total / totals["lessons"] if totals["lessons"] else Decimal(0)
        return {
            "range_total": str(total),
            "per_lesson_avg": str(money(per_lesson)),
            "month_to_date": str(money(month["total"])),
            "monthly_budget": str(money(self._budget if self._budget is not None else self._configured_budget())),
        }

    @staticmethod
    def _configured_budget() -> Decimal:
        return Decimal(str(settings.CONSOLE_MONTHLY_BUDGET_USD))


class CallSummary:
    def of(self, period: Period) -> dict:
        in_range = ModelCall.objects.filter(created_at__gte=period.start, created_at__lte=period.end)
        counts = in_range.aggregate(total=CallOutcomes.total(), **CallOutcomes.counts())
        return {key: counts[key] for key in ("total", "ok", "retried", "failed", "fallbacks")}


class DailySpend:
    """Spend per day and provider over the chart's days. Days without calls are included, empty."""

    def of(self, period: Period) -> list[dict]:
        dates = period.chart_dates()
        first = timezone.make_aware(datetime.combine(dates[0], datetime.min.time()))
        rows = (
            ModelCall.objects.filter(created_at__gte=first, created_at__lte=period.end, cost__isnull=False)
            .annotate(day=TruncDate("created_at"))
            .values("day", "provider_key")
            .annotate(spent=Sum("cost"))
        )
        by_day: dict = {date: {} for date in dates}
        for row in rows:
            by_day[row["day"]][row["provider_key"]] = str(money(row["spent"]))
        return [{"date": date.isoformat(), "by_provider": dict(sorted(by_day[date].items()))} for date in dates]


class DailyActivity:
    """Per day over the chart's days: lessons started, and model calls made and worked (ok on any attempt). These are
    the series behind the overview's sparklines. Days with nothing are included, as zeros."""

    def of(self, period: Period) -> list[dict]:
        dates = period.chart_dates()
        first = timezone.make_aware(datetime.combine(dates[0], datetime.min.time()))
        lessons = (
            Lesson.objects.filter(created_at__gte=first, created_at__lte=period.end)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(n=Count("id"))
        )
        calls = (
            ModelCall.objects.filter(created_at__gte=first, created_at__lte=period.end)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(total=Count("id"), worked=Count("id", filter=Q(status=ModelCall.Status.OK)))
        )
        by_day = {date: {"lessons_started": 0, "calls_total": 0, "calls_worked": 0} for date in dates}
        for row in lessons:
            by_day[row["day"]]["lessons_started"] = row["n"]
        for row in calls:
            by_day[row["day"]].update(calls_total=row["total"], calls_worked=row["worked"])
        return [{"date": date.isoformat(), **counts} for date, counts in by_day.items()]


class Funnel:
    """Where the lessons started in the range have got to. The counts overlap (a built lesson also answered its quick
    check); `failed_building` and `waiting` are where the rest stopped. Joins would repeat a lesson, so each count
    is distinct."""

    WAITING = (Stage.AWAITING_DIAGNOSTIC, Stage.AWAITING_PREREQUISITE, Stage.AWAITING_CHOICE)

    def of(self, period: Period) -> dict:
        def count(**filters):
            return Count("id", filter=Q(**filters) if filters else None, distinct=True)

        started = Lesson.objects.filter(created_at__gte=period.start, created_at__lte=period.end)
        ready = Q(stage=Stage.READY)
        return started.aggregate(
            started=count(),
            quick_check_done=count(quizzes__kind=Quiz.Kind.DIAGNOSTIC, quizzes__attempt__isnull=False),
            built=Count("id", filter=ready & ~Q(route=Route.MASTERY), distinct=True),
            test_submitted=count(submissions__isnull=False),
            study_sheets=Count("id", filter=ready & Q(route=Route.MASTERY), distinct=True),
            failed_building=count(stage=Stage.FAILED),
            waiting=count(stage__in=self.WAITING),
        )


class SlowestSteps:
    """The 95th percentile call time per step, from the calls that worked (an error that fails fast says nothing about
    speed), slowest first."""

    LIMIT = 6

    def of(self, period: Period) -> list[dict]:
        rows = (
            ModelCall.objects.filter(
                created_at__gte=period.start, created_at__lte=period.end, status=ModelCall.Status.OK
            )
            .values("node_key")
            .annotate(p95=PercentileCont("latency_ms", 0.95))
            .order_by("-p95", "node_key")[: self.LIMIT]
        )
        return [{"node": row["node_key"], "p95_s": round(row["p95"] / 1000, 3)} for row in rows]


class OverviewReport:
    def __init__(
        self,
        *,
        health: ConsoleHealth | None = None,
        lessons: LessonCounts | None = None,
        spend: SpendSummary | None = None,
        calls: CallSummary | None = None,
        daily: DailySpend | None = None,
        activity: DailyActivity | None = None,
        funnel: Funnel | None = None,
        slowest: SlowestSteps | None = None,
        attention: AttentionRules | None = None,
        periods: Periods | None = None,
    ):
        self.health = health or ConsoleHealth()
        self.lessons = lessons or LessonCounts()
        self.spend = spend or SpendSummary()
        self.calls = calls or CallSummary()
        self.daily = daily or DailySpend()
        self.activity = activity or DailyActivity()
        self.funnel = funnel or Funnel()
        self.slowest = slowest or SlowestSteps()
        self.attention = attention or AttentionRules()
        self.periods = periods or Periods()

    def build(self, range_key: str, now: datetime | None = None) -> dict:
        now = now or timezone.now()
        period = self.periods.of(range_key, now)
        return {
            "range": period.key,
            "period": {"start": self._iso(period.start), "end": self._iso(period.end)},
            "health": self.health.report(),
            "lessons": self.lessons.of(period),
            "spend": self.spend.of(period),
            "calls": self.calls.of(period),
            "daily_spend": self.daily.of(period),
            "daily_activity": self.activity.of(period),
            "funnel": self.funnel.of(period),
            "slowest_steps": self.slowest.of(period),
            "attention": [asdict(item) for item in self.attention.evaluate(AttentionContext(period, now))],
        }

    @staticmethod
    def _iso(moment: datetime) -> str:
        return moment.isoformat().replace("+00:00", "Z")

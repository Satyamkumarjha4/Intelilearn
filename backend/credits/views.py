"""The credits endpoints a learner can call (credits plan §8.1): the wallet, a quote, and the history. Every one is
owner-scoped; none makes a wallet; the quote runs the same code as the gate."""

from datetime import timedelta

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from lessons.models import Lesson

from .earning.days import StreakDays
from .earning.localday import LocalDay
from .earning.repair import StreakRepairService
from .earning.streak import StreakMilestones
from .earning.zone import LearnerZone
from .exempt import ExemptPolicy
from .ledger import Ledger
from .models import CreditBucket, CreditSettings, CreditTransaction, Plan, PlanPeriod, StreakDay
from .notices import ExpiryNotices
from .planner import SpendBucket, SpendPlanner
from .pricing.hints import UnknownHints
from .pricing.journey import JourneyQuote
from .quotes import QuoteAnswer
from .retry import RetryQuote
from .serializers import (
    BalanceSerializer,
    NoticesSerializer,
    PlansSerializer,
    QuoteRequestSerializer,
    QuoteSerializer,
    RepairResponseSerializer,
    RetryQuoteQuerySerializer,
    StreakSerializer,
    TransactionSerializer,
    WalletSerializer,
)
from .words import SubjectTitles, TransactionWords

TAGS = ["credits"]


class WalletView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="Your credits",
        description=(
            "The balance you can spend, what is set aside for work under way, the credits you can spend in the order "
            "they will be spent, and when the next ones run out. A read never creates anything."
        ),
        responses={200: WalletSerializer},
    )
    def get(self, request):
        ledger = Ledger()
        ledger.activate_periods(request.user)  # the new week's credits are here the moment the week starts
        now = ledger.clock.now()
        rows = CreditBucket.objects.filter(user=request.user, revoked_at__isnull=True, amount_remaining__gt=0)
        by_id = {row.pk: row for row in rows}
        spend = [SpendBucket(r.pk, r.amount_remaining, r.expires_at, r.created_at) for r in by_id.values()]
        ordered = [by_id[b.id] for b in SpendPlanner().in_order(spend, now)]
        dated = next((row for row in ordered if row.expires_at is not None), None)
        return Response(
            {
                "balance": sum(row.amount_remaining for row in ordered),
                "reserved": ledger.reserved(request.user),
                "buckets": [
                    {"source": r.source, "remaining": r.amount_remaining, "expires_at": r.expires_at} for r in ordered
                ],
                "next_expiry": {"at": dated.expires_at, "credits": dated.amount_remaining} if dated else None,
                "exempt": ExemptPolicy().applies_to(request.user),
            }
        )


class BalanceView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "credits_balance"

    @extend_schema(
        tags=TAGS,
        summary="Your balance, for the header",
        description=(
            "What you can spend, what is set aside for work under way, and how many notices about credits running "
            "out there are. Light enough to ask on every page; it says what the wallet says. A read makes no wallet."
        ),
        responses={200: BalanceSerializer},
    )
    def get(self, request):
        ledger = Ledger()
        ledger.activate_periods(request.user)
        return Response(
            {
                "balance": ledger.balance(request.user),
                "reserved": ledger.reserved(request.user),
                "notices": ExpiryNotices(ledger.clock).count(request.user),
            }
        )


class NoticesView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "credits_balance"

    @extend_schema(
        tags=TAGS,
        summary="Credits about to run out",
        description=(
            "Messages about credits that are close to running out, soonest first, counted in your own days. Credits "
            "that run out on the same day are one message. Worked out on every read; nothing is stored."
        ),
        responses={200: NoticesSerializer},
    )
    def get(self, request):
        ledger = Ledger()
        ledger.activate_periods(request.user)
        return Response({"notices": [n.as_json() for n in ExpiryNotices(ledger.clock).for_user(request.user)]})


class RetryQuoteView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "credits_quote"

    @extend_schema(
        tags=TAGS,
        summary="What Retry will cost",
        description=(
            "The price of trying a failed lesson again: what the stopped step asked for, priced now. Nothing is due "
            "when the work was kept. `400` for a lesson id that is not one, `404` for a lesson that is not yours."
        ),
        parameters=[RetryQuoteQuerySerializer],
        responses={200: QuoteSerializer},
    )
    def get(self, request):
        asked = RetryQuoteQuerySerializer(data=request.query_params)
        asked.is_valid(raise_exception=True)
        lesson = get_object_or_404(Lesson, pk=asked.validated_data["lesson"], owner=request.user)
        return Response(RetryQuote().of(lesson))


class QuoteView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "credits_quote"

    @extend_schema(
        tags=TAGS,
        summary="What something costs",
        description=(
            "The price of an action before you start it, line by line, with what is due now, what follows and the "
            "total. It runs the same rule the gate charges by. Only real actions and the hints they are asked with are "
            "accepted "
            "(`400` otherwise); a price the table lacks is `503 price_unavailable`."
        ),
        request=QuoteRequestSerializer,
        responses={200: QuoteSerializer},
    )
    def post(self, request):
        asked = QuoteRequestSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        action, size = asked.validated_data["action"], asked.validated_data["size"]
        try:
            journey = JourneyQuote().of(action, size)
        except UnknownHints as bad:
            raise ValidationError({"size": [str(bad)]}) from None
        return Response(QuoteAnswer.of(action, journey, request.user), status=status.HTTP_200_OK)


class TransactionCursorPagination(CursorPagination):
    ordering = "-id"
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class TransactionListView(generics.ListAPIView):
    pagination_class = TransactionCursorPagination
    serializer_class = TransactionSerializer

    def get_queryset(self):
        return CreditTransaction.objects.filter(user=self.request.user).select_related("hold")

    @extend_schema(
        tags=TAGS,
        summary="Your credit history",
        description="Newest first, in plain words, with the lesson or quiz each line was about when it still exists.",
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        words = TransactionWords(SubjectTitles.for_rows(page, request.user))
        return self.get_paginated_response([words.describe(row) for row in page])


class StreakView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="Your streak",
        description=(
            "The current and longest streak in your own time zone, whether today is done, the last 28 days, the next "
            "bonus and whether yesterday can be repaired. A read changes nothing."
        ),
        responses={200: StreakSerializer},
    )
    def get(self, request):
        ledger = Ledger()
        zone = LearnerZone.of(request.user)
        today = LocalDay.today(ledger.clock, zone).date
        days = StreakDays(ledger.clock)
        snapshot = days.snapshot(request.user, today)
        outlook = StreakRepairService(ledger=ledger, days=days).outlook(request.user, today)
        return Response(
            {
                "current": snapshot.current,
                "longest": snapshot.longest,
                "run_started_on": snapshot.run_started_on,
                "alive": snapshot.alive,
                "zone": zone,
                "today": {"date": today, "done": snapshot.done_today},
                "days": self._last_28(request.user, today),
                "next_bonus": self._next_bonus(snapshot.current if snapshot.alive else 0),
                "repair": {
                    "available": outlook.available,
                    "day": outlook.day,
                    "reason": outlook.reason,
                    "cost": outlook.cost,
                    "left_week": outlook.left_week,
                    "left_month": outlook.left_month,
                },
            }
        )

    @staticmethod
    def _last_28(user, today) -> list[dict]:
        first = today - timedelta(days=27)
        kinds = dict(StreakDay.objects.filter(user=user, local_date__gte=first).values_list("local_date", "kind"))
        out = []
        for n in range(28):
            day = first + timedelta(days=n)
            state = kinds.get(day) or ("pending" if day == today else "missed")
            out.append({"date": day, "state": state})
        return out

    @staticmethod
    def _next_bonus(current: int) -> dict:
        milestones = StreakMilestones()
        settings = CreditSettings.load()
        day = milestones.next_after(current)
        credits = settings.weekly_streak_bonus + (settings.monthly_streak_bonus if day % milestones.MONTH == 0 else 0)
        return {"streak_day": day, "credits": credits, "days_to_go": day - current}


class StreakRepairView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="Repair yesterday",
        description=(
            "Spends a credit to count yesterday as a day, if you missed it and the day before was a streak day, and "
            "the repair limits allow. `409 nothing_to_repair`, `409 repair_limit`, `402 insufficient_credits`."
        ),
        request=None,
        responses={200: RepairResponseSerializer},
    )
    def post(self, request):
        result = StreakRepairService().repair(request.user)
        streak = result.streak
        return Response(
            {
                "day": result.day,
                "cost": result.cost,
                "bonus": result.bonus,
                "streak": {
                    "current": streak.current,
                    "longest": streak.longest,
                    "run_started_on": streak.run_started_on,
                    "alive": streak.alive,
                },
            }
        )


class PlansView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="What you can buy",
        description=(
            "The plans on offer with their prices in paise, the rules for one-time credits, and your own running and "
            "waiting periods. Reading starts a period that is due, so the credits are there when the page is."
        ),
        responses={200: PlansSerializer},
    )
    def get(self, request):
        Ledger().activate_periods(request.user)
        settings = CreditSettings.load()
        plans = list(Plan.objects.filter(active=True))
        one_time = next((p for p in plans if p.is_one_time), None)
        periods = list(
            PlanPeriod.objects.filter(
                user=request.user, status__in=[PlanPeriod.Status.QUEUED, PlanPeriod.Status.ACTIVE]
            ).select_related("purchase__plan")
        )
        return Response(
            {
                "plans": [
                    {
                        "key": p.key,
                        "name": p.name,
                        "kind": "one_time" if p.is_one_time else "recurring",
                        "credits": p.credits,
                        "period_days": p.period_days,
                        "price_paise": p.price_paise,
                        "max_quantity": p.max_quantity,
                    }
                    for p in plans
                ],
                "one_time": {
                    "min_credits": settings.min_one_time_credits,
                    "max_credits": settings.max_one_time_credits,
                    "price_paise_per_credit": one_time.price_paise,
                    "valid_days": settings.purchased_valid_days,
                }
                if one_time
                else None,
                "periods": [
                    {
                        "plan": p.purchase.plan.key,
                        "plan_name": p.purchase.plan.name,
                        "status": p.status,
                        "starts_at": p.starts_at,
                        "ends_at": p.ends_at,
                        "credits": p.credits,
                    }
                    for p in periods
                ],
                "queue": {"open": len(periods), "limit": settings.max_queued_periods},
            }
        )

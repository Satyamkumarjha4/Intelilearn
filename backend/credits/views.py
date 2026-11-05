"""The credits endpoints a learner can call (credits plan §8.1): the wallet, a quote, and the history. Every one is
owner-scoped; none makes a wallet; the quote runs the same code as the gate."""

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .exempt import ExemptPolicy
from .ledger import Ledger
from .models import CreditBucket, CreditTransaction
from .planner import SpendBucket, SpendPlanner
from .pricing.hints import UnknownHints
from .pricing.journey import JourneyQuote
from .serializers import QuoteRequestSerializer, QuoteSerializer, TransactionSerializer, WalletSerializer
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
        now = ledger.clock.now()
        rows = CreditBucket.objects.filter(user=request.user, revoked_at__isnull=True, amount_remaining__gt=0)
        by_id = {row.pk: row for row in rows}
        spend = [SpendBucket(r.pk, r.amount_remaining, r.expires_at, r.created_at) for r in by_id.values()]
        ordered = [by_id[b.id] for b in SpendPlanner().in_order(spend, now)]
        dated = next((row for row in ordered if row.expires_at is not None), None)
        return Response(
            {
                "balance": sum(row.amount_remaining for row in ordered),
                "held": ledger.reserved(request.user),
                "buckets": [
                    {"source": r.source, "remaining": r.amount_remaining, "expires_at": r.expires_at} for r in ordered
                ],
                "next_expiry": {"at": dated.expires_at, "credits": dated.amount_remaining} if dated else None,
                "exempt": ExemptPolicy().applies_to(request.user),
            }
        )


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
        return Response(
            {
                "action": action,
                "lines": journey.due_now.as_json(),
                "due_now": journey.due_now.total,
                "later_lines": journey.later.as_json(),
                "later": journey.later.total,
                "total": journey.total,
                "exempt": ExemptPolicy().applies_to(request.user),
            },
            status=status.HTTP_200_OK,
        )


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

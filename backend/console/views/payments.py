from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response

from console.pagination import ConsoleCursorPagination
from console.serializers import UsageQuerySerializer
from console.serializers_credits import (
    PaymentPageSerializer,
    PaymentRowSerializer,
    RefundAttemptSerializer,
    RefundInputSerializer,
    RefundResultSerializer,
    RevenueSerializer,
    ShortfallSerializer,
)
from console.services.payments import PaymentsBoard
from console.services.revenue import RevenueReport
from payments.models import PaymentOrder, RefundAttempt
from payments.refunds import RefundDesk, RefundNotMarkable, RefundOutcome, RefundWords, RupeeAmount

from .base import CONSOLE_TAG, ConsoleListView, ConsoleView
from .usage import UsageFiltersMixin


class RefundRefused(APIException):
    """A refund that was not made, said in words a staff member can act on (the code is the outcome's kind)."""

    status_code = 409

    def __init__(self, kind: str, text: str):
        super().__init__(detail=text, code=kind)


class PaymentListView(ConsoleListView):
    serializer_class = PaymentRowSerializer

    class Pagination(ConsoleCursorPagination):
        ordering = "-created_at"

    pagination_class = Pagination

    def get_queryset(self):
        query = self.request.query_params
        return PaymentsBoard().orders(query.get("status", ""), query.get("gateway", ""), query.get("q", ""))

    def get_serializer(self, *args, **kwargs):
        if args and hasattr(args[0], "__iter__") and not isinstance(args[0], dict):
            args = ([PaymentsBoard().row(order) for order in args[0]], *args[1:])
        return super().get_serializer(*args, **kwargs)

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data["summary"] = PaymentsBoard().summary()
        return response

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Payments",
        description=(
            "Orders, newest first, with their state, gateway, amount, what was refunded and every refund asked for "
            "with its state. `summary` counts the refund and dispute events whose credits were already spent, refunds "
            "still waiting for the provider, and orders waiting for payment."
        ),
        parameters=[
            OpenApiParameter("status", str, description="created, pending, paid, fulfilled, failed or expired."),
            OpenApiParameter("gateway", str, description="stripe, razorpay…"),
            OpenApiParameter("q", str, description="The learner's name or email, or a provider reference."),
        ],
        responses={200: PaymentPageSerializer},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ShortfallListView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Credits a refund could not take back",
        description=(
            "Refund and dispute events whose credits had already been spent, newest first (the most recent 100): the "
            "amount that could not be taken back, for support to deal with."
        ),
        responses={200: ShortfallSerializer(many=True)},
    )
    def get(self, request):
        return Response(ShortfallSerializer(PaymentsBoard().shortfalls(), many=True).data)


class PaymentRefundView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Refund a payment",
        description=(
            "Asks the provider to refund all that remains of a fulfilled payment, or the `amount` (rupees) typed. The "
            "`token` is made when the form is drawn: a token refunds once however often it arrives, and is the "
            "provider's idempotency key where it has one. Never more than remains, counting refunds asked for and not "
            "yet confirmed. The credits come back when the provider's refund event arrives. Written to the change log. "
            "`409` with the reason's code for a refund that was not made."
        ),
        request=RefundInputSerializer,
        responses={200: RefundResultSerializer, 409: OpenApiResponse(description="Not made: the code says why.")},
    )
    def post(self, request, order_id):
        data = RefundInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            amount = RupeeAmount.to_paise(data.validated_data.get("amount", ""))
        except ValueError:
            raise ValidationError({"amount": ["Enter the amount in rupees, like 12.50."]}) from None
        if not PaymentOrder.objects.filter(pk=order_id).exists():
            raise Http404
        outcome = RefundDesk().refund(order_id, request.user, data.validated_data["token"], amount)
        level, text = RefundWords.of(outcome)
        if outcome.kind not in (RefundOutcome.ASKED, RefundOutcome.DUPLICATE):
            raise RefundRefused(outcome.kind, text[:1].upper() + text[1:])
        order = PaymentsBoard().orders().get(pk=order_id)
        body = {
            "kind": outcome.kind,
            "amount_paise": outcome.amount_paise,
            "message": text,
            "order": PaymentsBoard().row(order),
        }
        return Response(RefundResultSerializer(body).data)


class RefundMarkFailedView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Mark a refund as failed",
        description=(
            "Only for a refund the provider cannot be asked about (the sweep settles the rest). The amount it held can "
            "then be asked for again. Written to the change log. `409 not_markable` for one that is not waiting or "
            "that the provider can still be asked about."
        ),
        request=None,
        responses={200: RefundAttemptSerializer, 409: OpenApiResponse(description="`not_markable`.")},
    )
    def post(self, request, attempt_id):
        if not RefundAttempt.objects.filter(pk=attempt_id).exists():
            raise Http404
        try:
            attempt = RefundDesk().mark_failed(attempt_id, request.user)
        except RefundNotMarkable as refused:
            raise RefundRefused("not_markable", str(refused)) from None
        row = next(
            r
            for r in PaymentsBoard().row(PaymentsBoard().orders().get(pk=attempt.order_id))["refunds"]
            if r["id"] == attempt.pk
        )
        return Response(RefundAttemptSerializer(row).data)


class RevenueView(UsageFiltersMixin, ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Revenue beside model cost",
        description=(
            "Paid, refunded and net in rupees for the range, beside what model calls cost in it (recorded in dollars, "
            "shown in rupees at `usd_inr_rate`, the rate used) and what is left after it. The range is the usage "
            "page's; its other filters do not apply."
        ),
        parameters=[UsageQuerySerializer],
        responses={200: RevenueSerializer},
    )
    def get(self, request):
        return Response(RevenueSerializer(RevenueReport().build(self.filters(request).period)).data)

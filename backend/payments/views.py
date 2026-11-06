"""The payments endpoints (credits plan §8.2). Owner-scoped, except the webhook, which is signed instead."""

from django.core.exceptions import RequestDataTooBig
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from lessons.idempotency import IdempotentRequest

from .checkout import CheckoutService
from .errors import BodyTooLarge, InvalidWebhook, WebhookRefused
from .events import WebhookProcessor
from .models import PaymentOrder
from .presenters import OrderPresenter
from .reconcile import OrderReconciler
from .registry import PaymentGateways
from .serializers import (
    CreatedOrderSerializer,
    GatewaysSerializer,
    OrderRequestSerializer,
    OrderSerializer,
    OrdersSerializer,
    WebhookReceivedSerializer,
)

TAGS = ["payments"]


class GatewaysView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="Ways to pay",
        description="The payment gateways that are switched on, and the default. Empty when buying is not open.",
        responses={200: GatewaysSerializer},
    )
    def get(self, request):
        registry = PaymentGateways()
        default = registry.default()
        return Response(
            {
                "gateways": [{"key": g.key, "display_name": g.display_name} for g in registry.enabled()],
                "default": default.key if default else None,
            }
        )


class OrdersView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment_order"

    def get_throttles(self):
        return super().get_throttles() if self.request.method == "POST" else []  # only starting a payment is limited

    @extend_schema(
        tags=TAGS,
        summary="Start a payment",
        description=(
            "Prices a purchase on the server from the plan table, makes the order and asks the gateway for a checkout. "
            "The client sends a plan and a quantity or a number of credits, never a price. Supports `Idempotency-Key`. "
            "`400 invalid_plan`, `400 invalid_amount`, `400 gateway_not_enabled`, `409 queue_full`, "
            "`409 too_many_pending` (3 payments waiting), `502 gateway_unavailable` (nothing was charged)."
        ),
        request=OrderRequestSerializer,
        responses={201: CreatedOrderSerializer},
    )
    def post(self, request):
        asked = OrderRequestSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        data = asked.validated_data

        def start(_key: str) -> Response:
            order = CheckoutService().start(
                request.user, data["plan"], quantity=data["quantity"], credits=data.get("credits"),
                gateway=data.get("gateway"),
            )  # fmt: skip
            return Response(OrderPresenter.created(order), status=status.HTTP_201_CREATED)

        return IdempotentRequest().run(request, "payments.orders", dict(data), start)

    @extend_schema(
        tags=TAGS,
        summary="Your payments",
        description="The learner's payments, newest first (the most recent 50).",
        responses={200: OrdersSerializer},
        operation_id="payments_orders_list",
    )
    def get(self, request):
        orders = PaymentOrder.objects.filter(user=request.user).select_related("purchase__plan")[:50]
        return Response({"orders": [OrderPresenter.of(order) for order in orders]})


class OrderView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment_status"

    @extend_schema(
        tags=TAGS,
        summary="Where a payment stands",
        description=(
            "For the page the learner comes back to. It never grants anything itself: if the payment is still waiting "
            "after 30 seconds the server asks the provider (the same way the five-minute job does), and credits arrive "
            "only from that answer or from a signed callback. Another learner's order is a `404`."
        ),
        responses={200: OrderSerializer},
        operation_id="payments_order_retrieve",
    )
    def get(self, request, order_id):
        order = PaymentOrder.objects.select_related("purchase__plan").filter(pk=order_id, user=request.user).first()
        if order is None:
            raise NotFound("That payment was not found.")
        reconciler = OrderReconciler()
        if (
            order.status in PaymentOrder.OPEN
            and order.created_at <= reconciler.clock.now() - OrderReconciler.RETURN_WAIT
        ):
            order = reconciler.refresh(order)
        return Response(OrderPresenter.of(order))


@method_decorator(csrf_exempt, name="dispatch")
class WebhookView(APIView):
    """The provider's callback: no sign-in, no CSRF cookie (the only such view), the raw body, a size cap, and the
    signature proved before anything touches the database."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment_webhook"
    MAX_BYTES = 256 * 1024

    @extend_schema(
        tags=TAGS,
        summary="A provider's callback",
        description=(
            "Called by the payment provider, not by a browser. `200` for an applied or repeated event, `400` for a "
            "signature that does not verify, `404` for a gateway that is not on, `413` over 256 KB."
        ),
        request=None,
        auth=[],
        responses={200: WebhookReceivedSerializer, 400: OpenApiResponse(description="Not verified")},
    )
    def post(self, request, gateway):
        declared = request.META.get("CONTENT_LENGTH") or "0"
        if declared.isdigit() and int(declared) > self.MAX_BYTES:
            raise BodyTooLarge()
        try:
            raw = request.body
        except RequestDataTooBig:
            raise BodyTooLarge() from None
        if len(raw) > self.MAX_BYTES:
            raise BodyTooLarge()
        try:
            applied = WebhookProcessor().handle(gateway, request.headers, raw)
        except LookupError:
            raise Http404 from None
        except InvalidWebhook:
            raise WebhookRefused() from None
        return Response({"received": len(applied)})

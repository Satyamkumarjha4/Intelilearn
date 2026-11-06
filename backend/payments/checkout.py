"""Starting a payment (credits plan §5.8, T20).

The server decides everything that matters: the plan must be on, the amount is worked out from the plan table by
`PurchaseDesk` (the client names a plan and a quantity or a number of credits, never a price), the gateway must be one
that is switched on, and a learner may have only so many payments waiting at once. The order and its purchase are
written first, then the provider is asked for a checkout outside any transaction; a provider that cannot be reached
leaves the order failed and nothing granted.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction

from credits.clock import Clock
from credits.ledger import Ledger
from credits.models import CreditSettings, PlanPurchase
from credits.plans.desk import PurchaseDesk

from .errors import GatewayDown, GatewayUnavailable, TooManyPending
from .gateway import CheckoutOrder, ReturnUrls
from .lifecycle import OrderLifecycle
from .models import PaymentOrder
from .registry import PaymentGateways

logger = logging.getLogger(__name__)


class CheckoutService:
    #: how long an order waits for its payment before the reconciler lets it go
    ORDER_TTL = timedelta(hours=24)

    def __init__(
        self,
        gateways: PaymentGateways | None = None,
        desk: PurchaseDesk | None = None,
        lifecycle: OrderLifecycle | None = None,
        ledger: Ledger | None = None,
    ):
        self.ledger = ledger or Ledger()
        self.gateways = gateways or PaymentGateways()
        self.desk = desk or PurchaseDesk(ledger=self.ledger)
        self.lifecycle = lifecycle or OrderLifecycle(self.ledger.clock)

    @property
    def clock(self) -> Clock:
        return self.ledger.clock

    def start(
        self, user, plan_key: str, *, quantity: int = 1, credits: int | None = None, gateway: str | None = None
    ) -> PaymentOrder:
        """A pending order with its checkout, or a refusal (`gateway_not_enabled`, `invalid_plan`, `invalid_amount`,
        `queue_full`, `too_many_pending`, `gateway_unavailable`)."""
        provider = self.gateways.for_key(gateway)
        order = self._open(user, provider.key, plan_key, quantity, credits)
        urls = self._urls(order)
        try:
            session = provider.create_checkout(
                CheckoutOrder(
                    order_id=str(order.pk), amount_paise=order.amount_paise, currency=order.currency,
                    description=order.purchase.plan.name, buyer_email=getattr(user, "email", ""),
                ),
                urls,
            )  # fmt: skip
        except GatewayUnavailable:
            logger.exception("The %s checkout for order %s could not be made.", provider.key, order.pk)
            self.lifecycle.fail(order, "gateway_unavailable")
            raise GatewayDown() from None
        order.status, order.provider_ref, order.checkout = (
            PaymentOrder.Status.PENDING,
            session.provider_ref,
            session.as_json(),
        )
        order.expires_at = session.expires_at or self.clock.now() + self.ORDER_TTL
        order.save(update_fields=["status", "provider_ref", "checkout", "expires_at"])
        return order

    def _open(self, user, gateway_key: str, plan_key: str, quantity: int, credits: int | None) -> PaymentOrder:
        limit = CreditSettings.load().max_pending_orders
        with (
            transaction.atomic(),
            self.ledger.exclusive(user),
        ):  # the wallet lock makes the count and the insert one step
            waiting = PaymentOrder.objects.filter(user=user, status__in=PaymentOrder.OPEN).count()
            if waiting >= limit:
                raise TooManyPending()
            purchase: PlanPurchase = self.desk.open(user, plan_key, quantity=quantity, credits=credits)
            return PaymentOrder.objects.create(
                user=user, purchase=purchase, gateway=gateway_key, amount_paise=purchase.amount_paise,
                currency="INR", created_at=self.clock.now(),
            )  # fmt: skip

    @staticmethod
    def _urls(order: PaymentOrder) -> ReturnUrls:
        base = settings.PAYMENT_RETURN_BASE_URL
        return ReturnUrls(
            success=f"{base}/buy/return?order={order.pk}", cancel=f"{base}/buy/return?order={order.pk}&cancelled=1"
        )

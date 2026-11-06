"""Settling payments whose webhook was late or lost (credits plan §5.9, T24).

A webhook can fail to arrive, and a browser coming back from the provider proves nothing. So the server asks the
provider: `refresh` for one order (the return page's poll, once the order has been waiting a little), `run` for every
order that has waited long enough (every five minutes, from beat). An answer is turned into the same event a webhook
would have carried and applied the same way, so what it grants is granted once. `run` also retries a `paid` order that
was never fulfilled and lets go of an order whose deadline passed without a payment.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from credits.clock import Clock, SystemClock

from .errors import GatewayUnavailable
from .events import OrderEvents
from .fulfilment import FulfilmentService
from .gateway import PaymentEvent, PaymentStatus
from .lifecycle import OrderLifecycle
from .models import PaymentOrder
from .registry import PaymentGateways

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconcileReport:
    asked: int = 0
    settled: int = 0
    retried: int = 0
    expired: int = 0

    def as_dict(self) -> dict:
        return {"asked": self.asked, "settled": self.settled, "retried": self.retried, "expired": self.expired}


class OrderReconciler:
    WAIT = timedelta(minutes=15)  # an order is not asked about sooner than this by the sweep
    RETURN_WAIT = timedelta(seconds=30)  # nor sooner than this by the return page

    def __init__(
        self,
        gateways: PaymentGateways | None = None,
        events: OrderEvents | None = None,
        fulfilment: FulfilmentService | None = None,
        lifecycle: OrderLifecycle | None = None,
        clock: Clock | None = None,
    ):
        self.clock = clock or SystemClock()
        self.gateways = gateways or PaymentGateways()
        self.events = events or OrderEvents(clock=self.clock)
        self.fulfilment = fulfilment or FulfilmentService()
        self.lifecycle = lifecycle or OrderLifecycle(self.clock)

    def refresh(self, order: PaymentOrder) -> PaymentOrder:
        """Ask the provider about an open order and apply the answer. An unreachable provider changes nothing."""
        if order.status not in PaymentOrder.OPEN or not order.provider_ref:
            return order
        gateway = self.gateways.lookup(order.gateway)
        if gateway is None or gateway.missing_config():
            return order
        try:
            status = gateway.fetch_status(order.provider_ref)
        except GatewayUnavailable:
            logger.warning("Could not ask %s about order %s.", order.gateway, order.pk)
            return order
        event = self._event_of(order, status)
        if event is not None:
            self.events.apply(order.gateway, event)
            order.refresh_from_db()
        return order

    def run(self) -> ReconcileReport:
        now = self.clock.now()
        asked = settled = expired = retried = 0
        open_orders = PaymentOrder.objects.filter(status__in=PaymentOrder.OPEN, created_at__lte=now - self.WAIT)
        for order in open_orders.order_by("created_at"):
            if order.status == PaymentOrder.Status.CREATED and not order.provider_ref:
                self.lifecycle.fail(order, "checkout_not_made")  # the checkout never got made: nothing to ask about
                expired += 1
                continue
            asked += 1
            before = order.status
            self.refresh(order)
            if order.status != before:
                settled += 1
            elif order.status in PaymentOrder.OPEN and order.expires_at and order.expires_at <= now:
                expired += int(self.lifecycle.expire(order))
        for order in PaymentOrder.objects.filter(status=PaymentOrder.Status.PAID):
            self.fulfilment.fulfil(order)
            retried += 1
        return ReconcileReport(asked, settled, retried, expired)

    @staticmethod
    def _event_of(order: PaymentOrder, status: PaymentStatus) -> PaymentEvent | None:
        if status.state == PaymentStatus.PAID:
            kind = PaymentEvent.SUCCEEDED
        elif status.state in (PaymentStatus.FAILED, PaymentStatus.EXPIRED):
            kind = PaymentEvent.FAILED
        else:
            return None
        return PaymentEvent(
            event_id=f"status:{order.pk}:{kind}", kind=kind, provider_ref=order.provider_ref,
            amount_paise=status.amount_paise or order.amount_paise, currency=status.currency or order.currency,
            occurred_at=order.created_at, payment_ref=status.payment_ref,
        )  # fmt: skip

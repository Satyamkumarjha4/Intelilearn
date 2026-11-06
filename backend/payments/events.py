"""Applying what a provider says happened (credits plan T22, T23, §11).

`OrderEvents.apply` is the one place an event takes effect, whether it came in a webhook or was read off the provider by
the reconciler. It takes the order's row lock, refuses an event it has seen (the unique (gateway, event id) row),
compares the amount and the currency with the order, and writes the event row and the effect in the same transaction: an
event takes effect at most once, and a crash between the two leaves neither. `WebhookProcessor` is the front of it for a
callback: it proves the signature before any database work.
"""

import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from credits.clock import Clock, SystemClock

from .clawback import ClawbackService
from .errors import InvalidWebhook
from .fulfilment import FulfilmentService
from .gateway import PaymentEvent
from .lifecycle import OrderLifecycle
from .models import PaymentEventLog, PaymentOrder
from .registry import PaymentGateways

logger = logging.getLogger(__name__)
Outcome = PaymentEventLog.Outcome


@dataclass(frozen=True)
class Applied:
    outcome: str
    order_id: str = ""
    shortfall: int = 0


class OrderEvents:
    def __init__(
        self,
        fulfilment: FulfilmentService | None = None,
        clawback: ClawbackService | None = None,
        lifecycle: OrderLifecycle | None = None,
        clock: Clock | None = None,
    ):
        self.fulfilment = fulfilment or FulfilmentService()
        self.clawback = clawback or ClawbackService()
        self.lifecycle = lifecycle or OrderLifecycle()
        self.clock = clock or SystemClock()

    def apply(self, gateway_key: str, event: PaymentEvent) -> Applied:
        """Take `event` into account, once. A repeat of an event id is `duplicate` and changes nothing."""
        try:
            with transaction.atomic():
                return self._apply(gateway_key, event)
        except IntegrityError:  # two copies of one event raced to write its row; the other one won
            return Applied(Outcome.DUPLICATE)

    def _apply(self, gateway_key: str, event: PaymentEvent) -> Applied:
        order = None
        if event.provider_ref:
            order = (
                PaymentOrder.objects.select_for_update()
                .filter(gateway=gateway_key, provider_ref=event.provider_ref)
                .first()
            )
        if PaymentEventLog.objects.filter(gateway=gateway_key, event_id=event.event_id).exists():
            return Applied(Outcome.DUPLICATE, str(order.pk) if order else "")
        if order is None:
            logger.warning("A %s event %s from %s names no order we know.", event.kind, event.event_id, gateway_key)
            outcome, shortfall = Outcome.UNKNOWN_ORDER, 0
        elif (event.amount_paise, event.currency) != (order.amount_paise, order.currency) and self._amount_matters(
            event, order
        ):
            logger.error(
                "Order %s: the %s event %s says %s %s, the order is %s %s. Nothing was granted or taken back.",
                order.pk, event.kind, event.event_id, event.amount_paise, event.currency,
                order.amount_paise, order.currency,
            )  # fmt: skip
            outcome, shortfall = Outcome.AMOUNT_MISMATCH, 0
        else:
            outcome, shortfall = getattr(self, f"_{event.kind}")(order, event)
        PaymentEventLog.objects.create(
            gateway=gateway_key, event_id=event.event_id, kind=event.kind, order=order, provider_ref=event.provider_ref,
            amount_paise=event.amount_paise, currency=event.currency, outcome=outcome, shortfall=shortfall,
            received_at=self.clock.now(),
        )  # fmt: skip
        return Applied(outcome, str(order.pk) if order else "", shortfall)

    @staticmethod
    def _amount_matters(event: PaymentEvent, order: PaymentOrder) -> bool:
        """A success must be for exactly what was asked. A refund or dispute may be for part of it (and then only the
        currency has to match, and it may not be more than was paid); a failure carries no money."""
        if event.kind == PaymentEvent.SUCCEEDED:
            return True
        if event.kind == PaymentEvent.FAILED:
            return False
        return event.currency != order.currency or event.amount_paise > order.amount_paise

    def _succeeded(self, order: PaymentOrder, event: PaymentEvent) -> tuple[str, int]:
        if order.status == PaymentOrder.Status.FULFILLED:
            return Outcome.IGNORED, 0
        if order.status != PaymentOrder.Status.PAID:  # a late payment (after the order gave up) is still a payment
            order.status, order.paid_at = PaymentOrder.Status.PAID, self.clock.now()
            order.payment_ref = event.payment_ref or order.payment_ref
            order.save(update_fields=["status", "paid_at", "payment_ref"])
        self.fulfilment.fulfil(order)
        return Outcome.APPLIED, 0

    def _failed(self, order: PaymentOrder, event: PaymentEvent) -> tuple[str, int]:
        ended = self.lifecycle.fail(order, "payment_failed")
        return (Outcome.APPLIED if ended else Outcome.IGNORED), 0

    def _refunded(self, order: PaymentOrder, event: PaymentEvent) -> tuple[str, int]:
        if order.status not in (PaymentOrder.Status.PAID, PaymentOrder.Status.FULFILLED):
            return Outcome.IGNORED, 0  # nothing was granted, so there is nothing to take back
        if order.status == PaymentOrder.Status.PAID:
            self.fulfilment.fulfil(order)
        amount = min(event.amount_paise, order.amount_paise - order.refunded_paise)
        if amount <= 0:
            return Outcome.IGNORED, 0
        clawed = self.clawback.on_refund(order, amount)
        order.refunded_paise += amount
        order.save(update_fields=["refunded_paise"])
        return Outcome.APPLIED, clawed.shortfall

    _disputed = _refunded  # a dispute takes the money back like a refund does (D14)


class WebhookProcessor:
    def __init__(self, gateways: PaymentGateways | None = None, events: OrderEvents | None = None):
        self.gateways = gateways or PaymentGateways()
        self.events = events or OrderEvents()

    def handle(self, gateway_key: str, headers, raw_body: bytes) -> list[Applied]:
        """The result of each event in a callback. Raises `InvalidWebhook` for anything not proved, and `LookupError`
        for a gateway that is not on: in both nothing has touched the database."""
        gateway = next((g for g in self.gateways.enabled() if g.key == gateway_key), None)
        if gateway is None:
            raise LookupError(gateway_key)
        try:
            events = gateway.verify_webhook(headers, raw_body)
        except InvalidWebhook:
            raise
        except Exception as error:  # a parser that blew up on a hostile body is a bad webhook, not a server error
            raise InvalidWebhook("The body cannot be read.") from error
        return [self.events.apply(gateway.key, event) for event in events]

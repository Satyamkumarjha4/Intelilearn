"""Refunding a payment at an administrator's request (credits plan D14; phase 10.8 step 0).

`RefundDesk.refund` is the one place a refund is asked for. It works on the order under its row lock, so two submissions
of one form at the same moment are taken one after the other. The form's token makes a submission count once: the second
arrival finds its `RefundAttempt` and asks nothing. The token is also the provider's idempotency key where the provider
has one, so a request that was sent and whose answer never came back cannot be doubled by sending it again. Money is
never asked for beyond what remains: what was refunded, less what has been asked for and not yet confirmed by the
provider's refund event (a refund that failed no longer counts). The credits themselves come back only when that
event arrives, not here.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum

from console.audit import AuditTrail
from credits.clock import Clock, SystemClock

from .errors import PaymentError
from .models import PaymentOrder, RefundAttempt
from .registry import PaymentGateways


@dataclass(frozen=True)
class RefundOutcome:
    kind: str
    amount_paise: int = 0
    provider: str = ""  # the provider's name, for the "do it in their dashboard" outcome
    error: str = ""

    ASKED = "asked"
    DUPLICATE = "duplicate"  # this token was already used for this order: nothing was asked
    NOT_FULFILLED = "not_fulfilled"
    IN_FULL = "in_full"  # refunded in full already
    ALL_ASKED = "all_asked"  # all that remains has been asked for and is waiting for the provider
    TOO_MUCH = "too_much"  # more than remains; `amount_paise` is what does
    DASHBOARD = "dashboard"  # the provider cannot refund from here
    FAILED = "failed"


class RefundNotMarkable(Exception):
    """A person may not mark this attempt failed: it is not waiting, or the provider can still be asked."""


class RupeeAmount:
    """What an administrator types in the refund box: rupees, like `12.50`, as paise. Blank is no amount (the rest)."""

    @staticmethod
    def to_paise(text: str) -> int | None:
        """`None` for blank, else paise. `ValueError` for anything that is not a positive amount in whole paise."""
        text = (text or "").strip()
        if not text:
            return None
        try:
            rupees = Decimal(text)
        except InvalidOperation:
            raise ValueError(text) from None
        paise = rupees * 100
        if not rupees.is_finite() or paise <= 0 or paise != paise.to_integral_value():
            raise ValueError(text)
        return int(paise)


class RefundDesk:
    def __init__(self, gateways: PaymentGateways | None = None, clock: Clock | None = None):
        self.gateways = gateways or PaymentGateways()
        self.clock = clock or SystemClock()

    def refund(self, order_id, actor, token: uuid.UUID | None, amount_paise: int | None = None) -> RefundOutcome:
        """Ask for a refund of `amount_paise` (default: all that remains) of one order. `token` is the form's; without
        one the request is not de-duplicated (a fresh token is made, which still counts toward what has been asked)."""
        try:
            with transaction.atomic():
                order = PaymentOrder.objects.select_for_update().get(pk=order_id)
                return self._refund(order, actor, token, amount_paise)
        except (
            PaymentError
        ) as error:  # the provider refused or was down: nothing was written, so a resend can try again
            return RefundOutcome(RefundOutcome.FAILED, error=str(error))

    def _refund(self, order: PaymentOrder, actor, token: uuid.UUID | None, wanted: int | None) -> RefundOutcome:
        if order.status != PaymentOrder.Status.FULFILLED:
            return RefundOutcome(RefundOutcome.NOT_FULFILLED)
        if token and RefundAttempt.objects.filter(token=token, order=order).exists():
            return RefundOutcome(RefundOutcome.DUPLICATE)
        left = order.amount_paise - order.refunded_paise
        gateway = self.gateways.lookup(order.gateway)
        if left <= 0:
            return RefundOutcome(RefundOutcome.IN_FULL)
        if gateway is None or not gateway.can_refund or not order.payment_ref:
            return RefundOutcome(RefundOutcome.DASHBOARD, provider=gateway.display_name if gateway else order.gateway)
        available = left - self._unconfirmed(order)
        if available <= 0:
            return RefundOutcome(RefundOutcome.ALL_ASKED)
        amount = available if wanted is None else wanted
        if amount > available:
            return RefundOutcome(RefundOutcome.TOO_MUCH, amount_paise=available)
        token = token or uuid.uuid4()
        result = gateway.refund_with_key(order.payment_ref, amount, f"refund-{token}-{order.pk}")
        RefundAttempt.objects.create(
            token=token, order=order, amount_paise=amount, refund_ref=result.refund_ref,
            created_at=self.clock.now(),
        )  # fmt: skip
        AuditTrail(actor).record(
            "payments.refund", "payment_order", order.pk,
            after={
                "amount_paise": amount, "refund_ref": result.refund_ref, "gateway": order.gateway,
                "token": str(token),
            },
        )  # fmt: skip
        return RefundOutcome(RefundOutcome.ASKED, amount_paise=amount)

    def mark_failed(self, attempt_id, actor) -> RefundAttempt:
        """A person says a refund failed, for an attempt whose provider cannot be asked (a gateway that cannot
        answer, or one switched off for good). The amount it held is free to ask for again. Written to the change log.
        Refused for an attempt that is not waiting, and for one a provider can still be asked about: the sweep settles
        those."""
        with transaction.atomic():
            attempt = RefundAttempt.objects.select_related("order").get(pk=attempt_id)
            PaymentOrder.objects.select_for_update().get(pk=attempt.order_id)
            attempt.refresh_from_db()
            if attempt.state != RefundAttempt.State.PENDING:
                raise RefundNotMarkable("That refund is not waiting for an answer.")
            gateway = self.gateways.lookup(attempt.order.gateway)
            if gateway is not None and gateway.can_fetch_refund:
                raise RefundNotMarkable("The provider can still be asked about this one, and the sweep will do it.")
            before = attempt.state
            attempt.state, attempt.resolved_at = RefundAttempt.State.FAILED, self.clock.now()
            attempt.save(update_fields=["state", "resolved_at"])
            AuditTrail(actor).record(
                "payments.refund_failed", "refund_attempt", attempt.pk,
                before={"state": before, "amount_paise": attempt.amount_paise},
                after={"state": attempt.state, "amount_paise": attempt.amount_paise, "order": str(attempt.order_id)},
            )  # fmt: skip
        return attempt

    @staticmethod
    def _unconfirmed(order: PaymentOrder) -> int:
        """Refunds asked for that the provider has not yet confirmed: what was asked, less what has been confirmed. A
        refund made in the provider's own dashboard also counts as confirmed, so this can be too small, never too large;
        the provider itself refuses what is more than remains."""
        live = RefundAttempt.objects.filter(order=order).exclude(
            state=RefundAttempt.State.FAILED
        )  # a failed one is free
        asked = live.aggregate(total=Sum("amount_paise"))["total"] or 0
        return max(0, asked - order.refunded_paise)

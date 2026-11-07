"""Settling refunds an administrator asked for and has not heard back about (credits plan D14; phase 10.9 step 0).

A refund is asked for now and done later, and may fail. The provider says so in a webhook that can be late or lost, so
this asks. `RefundReconciler.run` goes over the attempts still waiting (older than a few minutes), asks the provider
about each through `fetch_refund`, and:

- a refund that is **processed** is applied as the event a webhook would have carried (the same id, `refund:<ref>`, so
  one that arrives later is a duplicate), which takes the credits back; the attempt becomes `confirmed`;
- a refund that **failed** becomes `failed`, and the amount it held is free to ask for again;
- one still pending is left alone.

A provider that cannot be asked (or cannot be reached) leaves the attempt waiting. For the first kind, a person can say
it failed in the console (`RefundDesk.mark_failed`).
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from credits.clock import Clock, SystemClock

from .errors import GatewayUnavailable, NotSupported
from .events import OrderEvents
from .gateway import PaymentEvent, RefundStatus
from .models import RefundAttempt
from .registry import PaymentGateways

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefundReport:
    asked: int = 0  # the provider gave an answer
    confirmed: int = 0
    failed: int = 0
    unanswerable: int = 0  # the provider cannot be asked about refunds
    unreachable: int = 0  # it could be, but did not answer

    def as_dict(self) -> dict:
        return {
            "asked": self.asked, "confirmed": self.confirmed, "failed": self.failed,
            "unanswerable": self.unanswerable, "unreachable": self.unreachable,
        }  # fmt: skip


class RefundReconciler:
    WAIT = timedelta(minutes=10)  # an attempt is not asked about sooner than this
    BATCH = 200  # at most this many in one run, oldest first

    def __init__(
        self,
        gateways: PaymentGateways | None = None,
        events: OrderEvents | None = None,
        clock: Clock | None = None,
    ):
        self.clock = clock or SystemClock()
        self.gateways = gateways or PaymentGateways()
        self.events = events or OrderEvents(clock=self.clock)

    def run(self) -> RefundReport:
        waiting = RefundAttempt.objects.filter(
            state=RefundAttempt.State.PENDING, created_at__lte=self.clock.now() - self.WAIT
        ).select_related("order")
        counts = {"asked": 0, "confirmed": 0, "failed": 0, "unanswerable": 0, "unreachable": 0}
        for attempt in waiting.order_by("created_at")[: self.BATCH]:
            gateway = self.gateways.lookup(attempt.order.gateway)
            if gateway is None or not gateway.can_fetch_refund or not attempt.refund_ref:
                counts["unanswerable"] += 1
                continue
            try:
                status = gateway.fetch_refund(attempt.refund_ref)
            except NotSupported:
                counts["unanswerable"] += 1
                continue
            except GatewayUnavailable:
                logger.warning("Could not ask %s about refund %s.", attempt.order.gateway, attempt.pk)
                counts["unreachable"] += 1
                continue
            counts["asked"] += 1
            if status.state == RefundStatus.PROCESSED:
                self._confirm(attempt, status)
                counts["confirmed"] += 1
            elif status.state == RefundStatus.FAILED:
                self._settle(attempt, RefundAttempt.State.FAILED)
                counts["failed"] += 1
        return RefundReport(**counts)

    def _confirm(self, attempt: RefundAttempt, status: RefundStatus) -> None:
        order = attempt.order
        self.events.apply(
            order.gateway,
            PaymentEvent(
                event_id=f"refund:{attempt.refund_ref}", kind=PaymentEvent.REFUNDED, provider_ref="",
                amount_paise=status.amount_paise or attempt.amount_paise, currency=order.currency,
                occurred_at=self.clock.now(), payment_ref=order.payment_ref,
            ),
        )  # fmt: skip
        self._settle(attempt, RefundAttempt.State.CONFIRMED)

    def _settle(self, attempt: RefundAttempt, state: str) -> None:
        attempt.state, attempt.resolved_at = state, self.clock.now()
        attempt.save(update_fields=["state", "resolved_at"])

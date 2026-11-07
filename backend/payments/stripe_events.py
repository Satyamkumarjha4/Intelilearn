"""What Stripe says when it calls the webhook (credits plan §6.4, T23): proving it is Stripe, then reading it.

`StripeSignature` is the proof, over the raw bytes of the body. `StripeEventReader` turns a proved event into the four
things the rest of the app understands (a payment that cleared, one that did not, a refund, a dispute). Both are pure:
no database, no network. Anything Stripe sends that is not ours to act on is an empty list, so a dashboard endpoint
subscribed to more events than we need is harmless.

A refund is counted from the refund object and not from `charge.refunded`. That event carries the charge's running
total, not the refund, and Stripe promises no order, so adding its figure would count a refund twice or a second partial
refund wrongly. `refund.created` and `refund.updated` both give the one refund, under one event id built from the
refund's own, so the order takes it once however many times Stripe says it.
"""

import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from .errors import InvalidWebhook
from .gateway import PaymentEvent


class StripeSignature:
    """`Stripe-Signature: t=<unix seconds>,v1=<hex>[,v1=<hex>…]`: HMAC-SHA256 of `"<t>.<body>"` with the endpoint's
    signing secret. More than one `v1` is a secret being rolled (Stripe signs with both for a day), and any one that
    matches is enough. Other schemes (`v0`, sent in test mode) are ignored, as Stripe asks, so nothing can downgrade
    the check. A signature older than the tolerance is refused: a captured request cannot be played again later."""

    def __init__(self, tolerance: timedelta = timedelta(minutes=5)):
        self.tolerance = tolerance

    def verify(self, header: str, raw_body: bytes, secret: str, now: datetime) -> None:
        """Returns when the signature is proved, else raises `InvalidWebhook`."""
        if not secret.strip():
            raise InvalidWebhook("No signing secret is set.")
        stamp, signatures = self._parse(header)
        if abs(now.timestamp() - stamp) > self.tolerance.total_seconds():
            raise InvalidWebhook("The signature is too old.")
        expected = hmac.new(secret.encode(), f"{stamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected.encode(), given.encode()) for given in signatures):
            raise InvalidWebhook("The signature does not match.")

    @staticmethod
    def _parse(header: str) -> tuple[int, list[str]]:
        stamp, signatures = "", []
        for part in header.split(","):
            name, _, value = part.strip().partition("=")
            if name == "t":
                stamp = value
            elif name == "v1" and value:
                signatures.append(value)
        if not stamp.isdigit() or not signatures:
            raise InvalidWebhook("The signature header cannot be read.")
        return int(stamp), signatures


class StripeEventReader:
    """One method per event type Stripe sends that we act on; the table below is the whole list. A new event is one
    method and one line."""

    def __init__(self) -> None:
        self._readers: dict[str, Callable[[str, dict, datetime], list[PaymentEvent]]] = {
            "checkout.session.completed": self._completed,
            "checkout.session.async_payment_succeeded": self._succeeded,
            "checkout.session.async_payment_failed": self._failed,
            "checkout.session.expired": self._failed,
            "refund.created": self._refunded,
            "refund.updated": self._refunded,
            "charge.dispute.created": self._disputed,
        }

    def read(self, event: object) -> list[PaymentEvent]:
        """The events in one Stripe event, or `[]` for one that is not ours. `InvalidWebhook` for a body that is not an
        event at all, or an event of ours that lacks what it needs."""
        if not (isinstance(event, dict) and isinstance(event.get("id"), str) and isinstance(event.get("type"), str)):
            raise InvalidWebhook("The body is not an event.")
        reader = self._readers.get(event["type"])
        if reader is None:
            return []
        try:
            when = datetime.fromtimestamp(int(event["created"]), UTC)
            return reader(event["id"], event["data"]["object"], when)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise InvalidWebhook("The event cannot be read.") from error

    def _completed(self, event_id: str, session: dict, when: datetime) -> list[PaymentEvent]:
        """Completed is not paid: a delayed method completes the session first and pays later (and then says so with
        `async_payment_succeeded`), so only a session that is paid now counts."""
        return self._succeeded(event_id, session, when) if session["payment_status"] == "paid" else []

    def _succeeded(self, event_id: str, session: dict, when: datetime) -> list[PaymentEvent]:
        return [self._session_event(PaymentEvent.SUCCEEDED, event_id, session, when)]

    def _failed(self, event_id: str, session: dict, when: datetime) -> list[PaymentEvent]:
        return [self._session_event(PaymentEvent.FAILED, event_id, session, when)]

    def _refunded(self, event_id: str, refund: dict, when: datetime) -> list[PaymentEvent]:
        if refund["status"] != "succeeded":  # pending ones come back as `refund.updated` when they succeed
            return []
        return [
            PaymentEvent(
                event_id=f"refund:{refund['id']}", kind=PaymentEvent.REFUNDED, provider_ref="",
                amount_paise=int(refund["amount"]), currency=str(refund["currency"]).upper(), occurred_at=when,
                payment_ref=self._ref(refund.get("payment_intent")),
            )
        ]  # fmt: skip

    def _disputed(self, event_id: str, dispute: dict, when: datetime) -> list[PaymentEvent]:
        return [
            PaymentEvent(
                event_id=event_id, kind=PaymentEvent.DISPUTED, provider_ref="", amount_paise=int(dispute["amount"]),
                currency=str(dispute["currency"]).upper(), occurred_at=when,
                payment_ref=self._ref(dispute.get("payment_intent")),
            )
        ]  # fmt: skip

    def _session_event(self, kind: str, event_id: str, session: dict, when: datetime) -> PaymentEvent:
        return PaymentEvent(
            event_id=event_id, kind=kind, provider_ref=str(session["id"]),
            amount_paise=int(session.get("amount_total") or 0), currency=str(session.get("currency") or "inr").upper(),
            occurred_at=when, payment_ref=self._ref(session.get("payment_intent")),
        )  # fmt: skip

    @staticmethod
    def _ref(value: object) -> str:
        """A payment intent is an id, or the object itself when Stripe was asked to expand it."""
        if isinstance(value, dict):
            value = value.get("id")
        return value if isinstance(value, str) else ""

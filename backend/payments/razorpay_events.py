"""What Razorpay says when it calls the webhook (credits plan §6.4, T23): proving it is Razorpay, then reading it.

`RazorpaySignature` is the proof: the hex HMAC-SHA256 of the raw body with the webhook secret (not the API key secret),
compared in constant time. Razorpay signs no timestamp, so a captured request verifies for ever; replay is stopped by
the event id it sends in `X-Razorpay-Event-Id`, which becomes the `PaymentEvent`'s id and so takes effect once. Both
classes are pure: no database, no network.

Which events count, and why:

- `order.paid` is the success. `payment.captured` and `payment.authorized` arrive beside it and say the same thing, so
  they are ignored: a success is counted once.
- `payment.failed` is one failed attempt, recorded and nothing more. A Razorpay order takes any number of attempts and
  the checkout window offers a retry, so a failure is not the end: the order ends only on a success or at our own
  deadline. A payment that does succeed on an order we had already let go of still grants.
- A refund is counted once it is `processed`, from `refund.created` or `refund.processed` (whichever says so), under the
  id `refund:<refund id>`, so the two are one event, as Stripe's are. It is found by its payment, which the order kept.
- `payment.dispute.created` takes the money back like a refund. The other dispute events say nothing: a lost dispute has
  already taken the credits back when it was raised.
"""

import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime

from .errors import InvalidWebhook
from .gateway import PaymentEvent


class RazorpaySignature:
    def verify(self, header: str, raw_body: bytes, secret: str) -> None:
        """Returns when the signature is proved, else raises `InvalidWebhook`."""
        if not secret.strip():
            raise InvalidWebhook("No webhook secret is set.")
        given = header.strip().lower()
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected.encode(), given.encode()):
            raise InvalidWebhook("The signature does not match.")


class RazorpayEventReader:
    """One method per event type we act on; the table is the whole list. A new event is one method and one line."""

    def __init__(self) -> None:
        self._readers: dict[str, Callable[[str, dict, datetime], list[PaymentEvent]]] = {
            "order.paid": self._paid,
            "payment.failed": self._failed,
            "refund.created": self._refunded,
            "refund.processed": self._refunded,
            "payment.dispute.created": self._disputed,
        }

    def read(self, event: object, event_id: str) -> list[PaymentEvent]:
        """The events in one Razorpay event (`event_id` is its header). `[]` for one that is not ours; `InvalidWebhook`
        for a body that is not an event, an event of ours that lacks what it needs, or one that has to be keyed by the
        header and has none."""
        if not (isinstance(event, dict) and isinstance(event.get("event"), str)):
            raise InvalidWebhook("The body is not an event.")
        reader = self._readers.get(event["event"])
        if reader is None:
            return []
        try:
            when = datetime.fromtimestamp(int(event["created_at"]), UTC)
            return reader(event_id.strip(), event["payload"], when)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise InvalidWebhook("The event cannot be read.") from error

    def _paid(self, event_id: str, payload: dict, when: datetime) -> list[PaymentEvent]:
        order = payload["order"]["entity"]
        if order["status"] != "paid":
            return []
        payment = payload.get("payment", {}).get("entity", {})
        return [
            PaymentEvent(
                event_id=self._keyed(event_id), kind=PaymentEvent.SUCCEEDED, provider_ref=str(order["id"]),
                amount_paise=int(order["amount_paid"]), currency=str(order["currency"]).upper(), occurred_at=when,
                payment_ref=str(payment.get("id") or ""),
            )
        ]  # fmt: skip

    def _failed(self, event_id: str, payload: dict, when: datetime) -> list[PaymentEvent]:
        payment = payload["payment"]["entity"]
        if not payment.get("order_id"):
            return []
        return [
            PaymentEvent(
                event_id=self._keyed(event_id), kind=PaymentEvent.ATTEMPT_FAILED, provider_ref=str(payment["order_id"]),
                amount_paise=int(payment.get("amount") or 0), currency=str(payment.get("currency") or "INR").upper(),
                occurred_at=when, payment_ref=str(payment["id"]),
            )
        ]  # fmt: skip

    def _refunded(self, event_id: str, payload: dict, when: datetime) -> list[PaymentEvent]:
        refund = payload["refund"]["entity"]
        if refund["status"] != "processed":  # a pending one comes back as `refund.processed`; a failed one never was
            return []
        return [
            PaymentEvent(
                event_id=f"refund:{refund['id']}", kind=PaymentEvent.REFUNDED, provider_ref="",
                amount_paise=int(refund["amount"]), currency=str(refund["currency"]).upper(), occurred_at=when,
                payment_ref=str(refund["payment_id"]),
            )
        ]  # fmt: skip

    def _disputed(self, event_id: str, payload: dict, when: datetime) -> list[PaymentEvent]:
        dispute = payload["dispute"]["entity"]
        return [
            PaymentEvent(
                event_id=self._keyed(event_id), kind=PaymentEvent.DISPUTED, provider_ref="",
                amount_paise=int(dispute["amount"]), currency=str(dispute["currency"]).upper(), occurred_at=when,
                payment_ref=str(dispute["payment_id"]),
            )
        ]  # fmt: skip

    @staticmethod
    def _keyed(event_id: str) -> str:
        """The header's id. Without it an event cannot be told from a replay, so it is refused rather than guessed."""
        if not event_id:
            raise ValueError("no event id")
        return event_id

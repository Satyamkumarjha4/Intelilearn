"""Stripe over plain HTTPS (credits plan §6.4, T21, D19). No SDK: a few `httpx` calls and the standard `hmac`.

`StripeApi` is the one place that talks to Stripe: it adds the pinned `Stripe-Version`, the secret key and an optional
idempotency key, and turns every way a call can fail into the port's errors without letting a key into a message.
`StripeGateway` is the port's implementation on top of it: a Checkout Session to pay on Stripe's own page, the signature
and event reading (`stripe_events`), a status lookup for a webhook that was lost, and a refund.

The API version is pinned, so Stripe's response shapes cannot change under us. Moving it is a reviewed change: set
`StripeApi.API_VERSION` to the new one, read its changelog, and run `pytest -m payments_live` against a test key.
Webhook payloads are rendered in the version of the endpoint they are sent to, not this one: create the endpoint (or run
`stripe listen --api-version`) with the same version.
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from urllib.parse import quote

import httpx

from credits.clock import Clock, SystemClock

from .config import GatewayConfig
from .errors import GatewayRejected, GatewayUnavailable, InvalidWebhook
from .gateway import (
    CheckoutOrder,
    CheckoutSession,
    PaymentEvent,
    PaymentGateway,
    PaymentStatus,
    RefundResult,
    ReturnUrls,
)
from .stripe_events import StripeEventReader, StripeSignature


class StripeApi:
    """Calls to `https://api.stripe.com/v1`. Form-encoded bodies, Basic auth with the secret key as the user name."""

    BASE_URL = "https://api.stripe.com"
    #: Pinned on every request (T21). Format `YYYY-MM-DD.<name>`; the current one is on docs.stripe.com/api/versioning.
    API_VERSION = "2026-10-28.endive"
    TIMEOUT = httpx.Timeout(15.0, connect=5.0)
    #: answers that are Stripe being busy or down, or our retry racing a first try: worth another attempt later
    TRY_AGAIN = {409, 429}

    def __init__(self, secret_key: str, client: httpx.Client | None = None):
        self._secret_key = secret_key
        self._client = client

    def post(self, path: str, form: Mapping[str, str], idempotency_key: str | None = None) -> dict:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return self._send("POST", path, data=dict(form), headers=headers)

    def get(self, path: str) -> dict:
        return self._send("GET", path)

    def _send(self, method: str, path: str, **kwargs) -> dict:
        headers = {"Stripe-Version": self.API_VERSION, **kwargs.pop("headers", {})}
        try:
            response = self._request(method, f"{self.BASE_URL}{path}", headers=headers, **kwargs)
        except httpx.HTTPError as error:  # no connection, a timeout, a dropped one: said by its class, never its text
            raise GatewayUnavailable(f"Stripe could not be reached ({type(error).__name__}).") from None
        return self._read(response)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        kwargs.update(auth=httpx.BasicAuth(self._secret_key, ""), timeout=self.TIMEOUT)
        if self._client is not None:
            return self._client.request(method, url, **kwargs)
        with httpx.Client() as client:
            return client.request(method, url, **kwargs)

    def _read(self, response: httpx.Response) -> dict:
        status = response.status_code
        if status >= 500 or status in self.TRY_AGAIN:
            raise GatewayUnavailable(f"Stripe is not able to answer just now (HTTP {status}).")
        if status >= 400:
            raise GatewayRejected(self._reason(response))
        try:
            body = response.json()
        except ValueError:
            raise GatewayUnavailable("Stripe's answer could not be read.") from None
        if not isinstance(body, dict):
            raise GatewayUnavailable("Stripe's answer could not be read.")
        return body

    def _reason(self, response: httpx.Response) -> str:
        """Why Stripe refused, in words safe to show staff. A bad key says only that; the rest is Stripe's own message
        (which names no secret), with this key struck out anyway and cut short."""
        status = response.status_code
        try:
            error = response.json()["error"]
            code = str(error.get("code") or "")
            text = str(error.get("message") or code or error.get("type") or "")
        except (ValueError, KeyError, TypeError, AttributeError):
            code = text = ""
        if status in (401, 403):  # the code (`api_key_expired`, say) is a fixed word; the message quotes the key
            why = f", {code[:60]}" if code else ""
            return f"Stripe did not accept the key (HTTP {status}{why}). Check STRIPE_SECRET_KEY."
        text = text.replace(self._secret_key, "***") if self._secret_key else text
        return f"Stripe refused the request (HTTP {status}){': ' + text[:200] if text else ''}"


class StripeGateway(PaymentGateway):
    key: ClassVar[str] = "stripe"
    display_name: ClassVar[str] = "Stripe"
    supported_currencies: ClassVar[tuple[str, ...]] = ("INR",)
    capabilities: ClassVar[frozenset[str]] = frozenset({PaymentGateway.REFUND})
    required_config: ClassVar[tuple[str, ...]] = ("secret_key", "webhook_secret")

    #: how long a Checkout Session stays open. Stripe allows 30 minutes to 24 hours; a little under the top, so the
    #: bound is never judged against a clock a second ahead of ours.
    CHECKOUT_TTL = timedelta(hours=23)
    SIGNATURE_HEADER = "Stripe-Signature"
    CANCELLED_REFUND = ("failed", "canceled")

    def __init__(
        self,
        config: GatewayConfig | None = None,
        client: httpx.Client | None = None,
        clock: Clock | None = None,
        signature: StripeSignature | None = None,
        events: StripeEventReader | None = None,
    ):
        super().__init__(config)
        self.api = StripeApi(self.config.get("secret_key"), client)
        self.clock = clock or SystemClock()
        self.signature = signature or StripeSignature()
        self.events = events or StripeEventReader()

    @classmethod
    def config_names(cls) -> dict[str, str]:
        return {"secret_key": "STRIPE_SECRET_KEY", "webhook_secret": "STRIPE_WEBHOOK_SECRET"}

    def create_checkout(self, order: CheckoutOrder, urls: ReturnUrls) -> CheckoutSession:
        """A Checkout Session in `payment` mode: the buyer is sent to Stripe's page, and comes back to `urls`. The order
        id is the idempotency key, so a second try of the same order cannot make a second session."""
        expires = self.clock.now() + self.CHECKOUT_TTL
        form = {
            "mode": "payment",
            "client_reference_id": order.order_id,
            "metadata[order_id]": order.order_id,
            "payment_intent_data[metadata][order_id]": order.order_id,
            "success_url": urls.success,
            "cancel_url": urls.cancel,
            "expires_at": str(int(expires.timestamp())),
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": order.currency.lower(),
            "line_items[0][price_data][unit_amount]": str(order.amount_paise),
            "line_items[0][price_data][product_data][name]": order.description,
        }
        if order.buyer_email:
            form["customer_email"] = order.buyer_email
        session = self.api.post("/v1/checkout/sessions", form, idempotency_key=order.order_id)
        if not (isinstance(session.get("id"), str) and isinstance(session.get("url"), str)):
            raise GatewayUnavailable("Stripe's answer had no Checkout Session in it.")
        return CheckoutSession(
            kind=CheckoutSession.REDIRECT,
            provider_ref=session["id"],
            redirect_url=session["url"],
            expires_at=self._moment(session.get("expires_at")) or expires,
        )

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> list[PaymentEvent]:
        given = next((v for k, v in headers.items() if k.lower() == self.SIGNATURE_HEADER.lower()), "")
        self.signature.verify(given, raw_body, self.config.get("webhook_secret"), self.clock.now())

        try:
            event = json.loads(raw_body)
        except ValueError as error:
            raise InvalidWebhook("The body cannot be read.") from error
        return self.events.read(event)

    def fetch_status(self, provider_ref: str) -> PaymentStatus:
        """Open or complete-but-unpaid is `pending` (a delayed method settles later and then sends its own event); paid
        is `paid`; an expired session is `expired`."""
        session = self.api.get(f"/v1/checkout/sessions/{quote(provider_ref, safe='')}")
        if session.get("payment_status") == "paid":
            intent = session.get("payment_intent")
            return PaymentStatus(
                state=PaymentStatus.PAID,
                amount_paise=int(session.get("amount_total") or 0),
                currency=str(session.get("currency") or "inr").upper(),
                payment_ref=intent if isinstance(intent, str) else "",
            )
        if session.get("status") == "expired":
            return PaymentStatus(state=PaymentStatus.EXPIRED)
        return PaymentStatus(state=PaymentStatus.PENDING)

    def refund(self, payment_ref: str, amount_paise: int) -> RefundResult:
        """Refund `amount_paise` of a payment (a payment intent id), with no idempotency key (`refund_with_key`)."""
        return self._refund(payment_ref, amount_paise, None)

    def refund_with_key(self, payment_ref: str, amount_paise: int, idempotency_key: str) -> RefundResult:
        """The admin's form sends one key per submission, so a double click, or a request whose answer was lost, is one
        refund at Stripe; a second, deliberate refund is another submission and has another key."""
        return self._refund(payment_ref, amount_paise, idempotency_key)

    def _refund(self, payment_ref: str, amount_paise: int, idempotency_key: str | None) -> RefundResult:
        if not payment_ref:
            raise GatewayRejected("There is no payment to refund.")
        form = {"payment_intent": payment_ref, "amount": str(amount_paise)}
        refund = self.api.post("/v1/refunds", form, idempotency_key=idempotency_key)
        if refund.get("status") in self.CANCELLED_REFUND or not isinstance(refund.get("id"), str):
            raise GatewayRejected("Stripe did not make the refund.")
        return RefundResult(refund_ref=refund["id"], amount_paise=int(refund.get("amount") or amount_paise))

    @staticmethod
    def _moment(seconds: object) -> datetime | None:
        return datetime.fromtimestamp(seconds, UTC) if isinstance(seconds, int) else None

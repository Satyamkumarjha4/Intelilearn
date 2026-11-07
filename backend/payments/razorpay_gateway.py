"""Razorpay over plain HTTPS (credits plan §6.4, T21, D19, D20). No SDK: a few `httpx` calls and the standard `hmac`.

Razorpay's checkout is on our own page: the server makes an Order (so the amount is the server's and the learner cannot
change it) and hands the browser the public parameters to open Razorpay's checkout with. `RazorpayApi` is the one place
that talks to Razorpay: Basic auth with the key id and secret, JSON bodies, and every failure turned into the port's
errors without a key in a message. Razorpay is versioned by path (`/v1`), so there is no version to pin.

Two things the checkout depends on, set in the Razorpay dashboard, not in code: payments are captured automatically (the
default; `order.paid` is only sent once a payment is captured), and the webhook is subscribed to `order.paid`,
`payment.failed`, `refund.created`, `refund.processed` and `payment.dispute.created`.
"""

import json
from collections.abc import Mapping
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
from .razorpay_events import RazorpayEventReader, RazorpaySignature


class RazorpayApi:
    """Calls to `https://api.razorpay.com/v1`."""

    BASE_URL = "https://api.razorpay.com"
    TIMEOUT = httpx.Timeout(15.0, connect=5.0)
    #: Razorpay being busy, or a retry racing its first try: worth another attempt later
    TRY_AGAIN = {409, 429}

    def __init__(self, key_id: str, key_secret: str, client: httpx.Client | None = None):
        self._key_id = key_id
        self._key_secret = key_secret
        self._client = client

    def post(self, path: str, body: Mapping[str, object], headers: Mapping[str, str] | None = None) -> dict:
        return self._send("POST", path, json=dict(body), headers=dict(headers or {}))

    def get(self, path: str) -> dict:
        return self._send("GET", path)

    def _send(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._request(method, f"{self.BASE_URL}{path}", **kwargs)
        except httpx.HTTPError as error:  # no connection, a timeout, a dropped one: said by its class, never its text
            raise GatewayUnavailable(f"Razorpay could not be reached ({type(error).__name__}).") from None
        return self._read(response)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        kwargs.update(auth=httpx.BasicAuth(self._key_id, self._key_secret), timeout=self.TIMEOUT)
        if self._client is not None:
            return self._client.request(method, url, **kwargs)
        with httpx.Client() as client:
            return client.request(method, url, **kwargs)

    def _read(self, response: httpx.Response) -> dict:
        status = response.status_code
        if status >= 500 or status in self.TRY_AGAIN:
            raise GatewayUnavailable(f"Razorpay is not able to answer just now (HTTP {status}).")
        if status >= 400:
            raise GatewayRejected(self._reason(response))
        try:
            body = response.json()
        except ValueError:
            raise GatewayUnavailable("Razorpay's answer could not be read.") from None
        if not isinstance(body, dict):
            raise GatewayUnavailable("Razorpay's answer could not be read.")
        return body

    def _reason(self, response: httpx.Response) -> str:
        """Why Razorpay refused, in words safe to show staff: its own description, with both keys struck out anyway and
        cut short. A 401 says only which settings to check (a bad key is often a 400 and says so in the description)."""
        status = response.status_code
        if status == 401:
            return "Razorpay did not accept the keys (HTTP 401). Check RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET."
        try:
            error = response.json()["error"]
            text = str(error.get("description") or error.get("reason") or error.get("code") or "")
        except (ValueError, KeyError, TypeError, AttributeError):
            text = ""
        for secret in (self._key_secret, self._key_id):
            text = text.replace(secret, "***") if secret else text
        return f"Razorpay refused the request (HTTP {status}){': ' + text[:200] if text else ''}"


class RazorpayGateway(PaymentGateway):
    key: ClassVar[str] = "razorpay"
    display_name: ClassVar[str] = "Razorpay"
    supported_currencies: ClassVar[tuple[str, ...]] = ("INR",)
    capabilities: ClassVar[frozenset[str]] = frozenset({PaymentGateway.REFUND})
    required_config: ClassVar[tuple[str, ...]] = ("key_id", "key_secret", "webhook_secret")

    ADAPTER = "razorpay"  # the name the frontend picks its code by
    CHECKOUT_NAME = "Socra"  # the business name on Razorpay's form
    RECEIPT_MAX = 40  # Razorpay's limit for an order's receipt
    SIGNATURE_HEADER = "X-Razorpay-Signature"
    EVENT_ID_HEADER = "X-Razorpay-Event-Id"
    REFUND_KEY_HEADER = "X-Refund-Idempotency"

    def __init__(
        self,
        config: GatewayConfig | None = None,
        client: httpx.Client | None = None,
        clock: Clock | None = None,
        signature: RazorpaySignature | None = None,
        events: RazorpayEventReader | None = None,
    ):
        super().__init__(config)
        self.api = RazorpayApi(self.config.get("key_id"), self.config.get("key_secret"), client)
        self.clock = clock or SystemClock()
        self.signature = signature or RazorpaySignature()
        self.events = events or RazorpayEventReader()

    @classmethod
    def config_names(cls) -> dict[str, str]:
        return {
            "key_id": "RAZORPAY_KEY_ID",
            "key_secret": "RAZORPAY_KEY_SECRET",
            "webhook_secret": "RAZORPAY_WEBHOOK_SECRET",
        }

    def create_checkout(self, order: CheckoutOrder, urls: ReturnUrls) -> CheckoutSession:
        """An Order with our order id as its receipt and in its notes, and the public parameters to open Razorpay's
        checkout with: the key id (public), Razorpay's order id, the amount and currency, and a name. Retry is off, so a
        failed attempt ends the checkout (and `payment.failed` ends our order). Nothing secret is returned."""
        body = {
            "amount": order.amount_paise,
            "currency": order.currency,
            "receipt": order.order_id[: self.RECEIPT_MAX],
            "notes": {"order_id": order.order_id},
        }
        created = self.api.post("/v1/orders", body)
        if not isinstance(created.get("id"), str):
            raise GatewayUnavailable("Razorpay's answer had no order in it.")
        client: dict[str, object] = {
            "key": self.config.get("key_id"),
            "order_id": created["id"],
            "amount": order.amount_paise,
            "currency": order.currency,
            "name": self.CHECKOUT_NAME,
            "description": order.description,
            "retry": {"enabled": False},
        }
        if order.buyer_email:
            client["prefill"] = {"email": order.buyer_email}
        return CheckoutSession(
            kind=CheckoutSession.CLIENT, provider_ref=created["id"], client=client, adapter=self.ADAPTER
        )

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> list[PaymentEvent]:
        lowered = {name.lower(): value for name, value in headers.items()}
        self.signature.verify(
            lowered.get(self.SIGNATURE_HEADER.lower(), ""), raw_body, self.config.get("webhook_secret")
        )
        try:
            event = json.loads(raw_body)
        except ValueError as error:
            raise InvalidWebhook("The body cannot be read.") from error
        return self.events.read(event, lowered.get(self.EVENT_ID_HEADER.lower(), ""))

    def fetch_status(self, provider_ref: str) -> PaymentStatus:
        """`paid` once the order is paid (then its payments say which one was taken); otherwise `pending`. An order can
        take another attempt after a failed one and does not expire by itself, so it is never `failed` or `expired`
        from here: a failure comes by webhook and the order's own deadline is ours."""
        reference = quote(provider_ref, safe="")
        order = self.api.get(f"/v1/orders/{reference}")
        if order.get("status") != "paid":
            return PaymentStatus(state=PaymentStatus.PENDING)
        payments = self.api.get(f"/v1/orders/{reference}/payments").get("items") or []
        taken = next((p for p in payments if p.get("status") in ("captured", "refunded") or p.get("captured")), {})
        return PaymentStatus(
            state=PaymentStatus.PAID,
            amount_paise=int(order.get("amount_paid") or 0),
            currency=str(order.get("currency") or "INR").upper(),
            payment_ref=str(taken.get("id") or ""),
        )

    def refund(self, payment_ref: str, amount_paise: int) -> RefundResult:
        """Refund `amount_paise` of a payment (a `pay_` id), with no idempotency key (see `refund_with_key`)."""
        return self._refund(payment_ref, amount_paise, None)

    def refund_with_key(self, payment_ref: str, amount_paise: int, idempotency_key: str) -> RefundResult:
        """The admin's form sends one key per submission (`X-Refund-Idempotency`: 10 or more of letters, digits, hyphens
        and underscores), so a double click, or a request whose answer was lost, is one refund at Razorpay."""
        return self._refund(payment_ref, amount_paise, idempotency_key)

    def _refund(self, payment_ref: str, amount_paise: int, idempotency_key: str | None) -> RefundResult:
        if not payment_ref:
            raise GatewayRejected("There is no payment to refund.")
        headers = {self.REFUND_KEY_HEADER: idempotency_key} if idempotency_key else {}
        refund = self.api.post(f"/v1/payments/{quote(payment_ref, safe='')}/refund", {"amount": amount_paise}, headers)
        if refund.get("status") == "failed" or not isinstance(refund.get("id"), str):
            raise GatewayRejected("Razorpay did not make the refund.")
        return RefundResult(refund_ref=refund["id"], amount_paise=int(refund.get("amount") or amount_paise))

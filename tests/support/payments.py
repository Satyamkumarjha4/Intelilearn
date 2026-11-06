"""Fixtures and a test double for the payment tests (credits plan §13.3).

`ScriptedGateway` subclasses the real `PaymentGateway`, so it proves the port can be implemented by something other than
the fake gateway the app ships. It signs its own callbacks, records every call made to it, and answers `fetch_status`
and `create_checkout` from a script a test sets. The `payments` fixture registers it, switches it on as the only
(default) gateway, and gives back a `Payments` to buy, to send events and to read what happened.

The models are imported inside the fixtures, because this module is loaded before Django is set up.
"""

import hashlib
import hmac
import itertools
import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

SECRET = "scripted-gateway-secret"


def sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class Script:
    """What the scripted gateway has been asked and what it will answer. One per test."""

    def __init__(self):
        self.checkouts: list = []
        self.statuses: dict[str, object] = {}
        self.refunds: list[tuple[str, int]] = []
        self.checkout_error: Exception | None = None
        self.status_error: Exception | None = None
        self.status_calls: list[str] = []


SCRIPT = Script()


def _gateway_class():
    from payments.errors import InvalidWebhook
    from payments.gateway import CheckoutSession, PaymentEvent, PaymentGateway, PaymentStatus, RefundResult

    class ScriptedGateway(PaymentGateway):
        key = "scripted"
        display_name = "Scripted payments"
        capabilities = frozenset({PaymentGateway.REFUND})
        required_config = ("webhook_secret",)

        @classmethod
        def config_names(cls):
            return {"webhook_secret": "PAYMENT_FAKE_GATEWAY_SECRET"}

        def create_checkout(self, order, urls):
            SCRIPT.checkouts.append((order, urls))
            if SCRIPT.checkout_error:
                raise SCRIPT.checkout_error
            return CheckoutSession(
                kind=CheckoutSession.REDIRECT, provider_ref=f"ref_{order.order_id}", redirect_url=urls.success
            )

        def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes):
            given = next((v for k, v in headers.items() if k.lower() == "x-scripted-signature"), "")
            if not hmac.compare_digest(given, sign(raw_body, self.config.get("webhook_secret"))):
                raise InvalidWebhook("bad signature")
            try:
                data = json.loads(raw_body)
                return [
                    PaymentEvent(
                        event_id=item["id"], kind=item["kind"], provider_ref=item["provider_ref"],
                        amount_paise=item["amount_paise"], currency=item.get("currency", "INR"),
                        occurred_at=datetime.fromisoformat(item["occurred_at"]),
                        payment_ref=item.get("payment_ref", ""),
                    )
                    for item in data["events"]
                ]  # fmt: skip
            except (KeyError, ValueError, TypeError) as error:
                raise InvalidWebhook("unreadable") from error

        def fetch_status(self, provider_ref):
            SCRIPT.status_calls.append(provider_ref)
            if SCRIPT.status_error:
                raise SCRIPT.status_error
            return SCRIPT.statuses.get(provider_ref, PaymentStatus(state=PaymentStatus.PENDING))

        def refund(self, payment_ref, amount_paise):
            SCRIPT.refunds.append((payment_ref, amount_paise))
            return RefundResult(refund_ref=f"refund_{payment_ref}", amount_paise=amount_paise)

    return ScriptedGateway


class Payments:
    """What a payment test does: buy, have the provider say something, and read the result."""

    def __init__(self, user, gateway_cls):
        self.user = user
        self.gateway_cls = gateway_cls
        self.script = SCRIPT
        self._ids = itertools.count(1)

    # --- buying
    def buy(self, plan="one_time", *, credits=100, quantity=1, user=None):
        """A pending order, made the way the API makes it."""
        from payments.checkout import CheckoutService

        kwargs = {"credits": credits} if plan == "one_time" else {"quantity": quantity}
        return CheckoutService().start(user or self.user, plan, **kwargs)

    # --- what the provider says
    def body(self, kind, order, *, amount=None, event_id=None, currency="INR", payment_ref="pay_1", at=None):
        event = {
            "id": event_id or f"evt_{next(self._ids)}", "kind": kind, "provider_ref": order.provider_ref,
            "amount_paise": order.amount_paise if amount is None else amount, "currency": currency,
            "occurred_at": (at or datetime.now(UTC)).isoformat(), "payment_ref": payment_ref,
        }  # fmt: skip
        return json.dumps({"events": [event]}).encode()

    def headers(self, body: bytes, secret: str = SECRET) -> dict[str, str]:
        return {"X-Scripted-Signature": sign(body, secret)}

    def send(self, kind, order, **kwargs):
        """Hand the processor a signed event, as the webhook view does."""
        from payments.events import WebhookProcessor

        body = self.body(kind, order, **kwargs)
        return WebhookProcessor().handle("scripted", self.headers(body), body)

    def post(self, client, kind, order, *, signed=True, **kwargs):
        """The same, through the HTTP endpoint."""
        body = self.body(kind, order, **kwargs)
        headers = self.headers(body) if signed else {"X-Scripted-Signature": "nope"}
        return client.generic(
            "POST", "/api/payments/webhooks/scripted", body, content_type="application/json",
            HTTP_X_SCRIPTED_SIGNATURE=headers["X-Scripted-Signature"],
        )  # fmt: skip

    def says_paid(self, order, amount=None, currency="INR"):
        from payments.gateway import PaymentStatus

        self.script.statuses[order.provider_ref] = PaymentStatus(
            state=PaymentStatus.PAID,
            amount_paise=order.amount_paise if amount is None else amount,
            currency=currency,
            payment_ref="pay_status",
        )

    def says(self, order, state):
        from payments.gateway import PaymentStatus

        self.script.statuses[order.provider_ref] = PaymentStatus(state=state)


@pytest.fixture
def payments(db, user, monkeypatch, settings):
    """The scripted gateway, registered, switched on as the only one, and a `Payments` to drive it. The plans the
    spec sells are in the table."""
    from credits.plans.seed import PlanSeed
    from payments.registry import PaymentGateways

    global SCRIPT
    SCRIPT.__init__()
    gateway = _gateway_class()
    monkeypatch.setitem(PaymentGateways.REGISTERED, gateway.key, gateway)
    settings.PAYMENT_GATEWAYS_ENABLED = [gateway.key]
    settings.PAYMENT_DEFAULT_GATEWAY = gateway.key
    settings.PAYMENT_FAKE_GATEWAY_SECRET = SECRET
    settings.PAYMENT_RETURN_BASE_URL = "http://shop.test"
    PlanSeed().apply()
    return Payments(user, gateway)

"""The fake gateway (credits plan T26): the whole buying path in a browser with no provider and no key.

It is registered only when `PAYMENT_ALLOW_FAKE_GATEWAY` is true, which is the throwaway test stack and nothing else, and
a system check refuses to start with it enabled otherwise. Its "provider page" is the return page itself: a test "pays"
by sending a signed webhook, exactly as a provider does, with a secret read from the environment
(`PAYMENT_FAKE_GATEWAY_SECRET`). It has nothing to ask about a payment, so `fetch_status` says pending.
"""

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import datetime

from django.conf import settings

from .errors import InvalidWebhook
from .gateway import (
    CheckoutOrder,
    CheckoutSession,
    PaymentEvent,
    PaymentGateway,
    PaymentStatus,
    RefundResult,
    ReturnUrls,
)


class FakeGateway(PaymentGateway):
    key = "fake"
    display_name = "Test payments"
    capabilities = frozenset({PaymentGateway.REFUND})
    required_config = ("webhook_secret",)

    SIGNATURE_HEADER = "X-Fake-Signature"

    @classmethod
    def config_names(cls) -> dict[str, str]:
        return {"webhook_secret": "PAYMENT_FAKE_GATEWAY_SECRET"}

    def create_checkout(self, order: CheckoutOrder, urls: ReturnUrls) -> CheckoutSession:
        return CheckoutSession(
            kind=CheckoutSession.REDIRECT, provider_ref=f"fake_{order.order_id}", redirect_url=urls.success
        )

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> list[PaymentEvent]:
        given = next((v for k, v in headers.items() if k.lower() == self.SIGNATURE_HEADER.lower()), "")
        if not hmac.compare_digest(given.strip(), self.sign(self.config.get("webhook_secret"), raw_body)):
            raise InvalidWebhook("The signature does not match.")
        try:
            data = json.loads(raw_body)
            kind = data["type"]
            if kind not in PaymentEvent.KINDS:
                raise InvalidWebhook(f"'{kind}' is not an event this gateway knows.")
            return [
                PaymentEvent(
                    event_id=str(data["id"]), kind=kind, provider_ref=str(data["provider_ref"]),
                    amount_paise=int(data["amount_paise"]), currency=str(data.get("currency", "INR")),
                    occurred_at=datetime.fromisoformat(data["occurred_at"]),
                    payment_ref=str(data.get("payment_ref", "")),
                )
            ]  # fmt: skip
        except (ValueError, KeyError, TypeError) as error:
            raise InvalidWebhook("The body cannot be read.") from error

    def fetch_status(self, provider_ref: str) -> PaymentStatus:
        return PaymentStatus(state=PaymentStatus.PENDING)

    def refund(self, payment_ref: str, amount_paise: int) -> RefundResult:
        return RefundResult(refund_ref=f"fake_refund_{payment_ref}", amount_paise=amount_paise)

    @staticmethod
    def sign(secret: str, raw_body: bytes) -> str:
        return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()

    @staticmethod
    def secret() -> str:
        return settings.PAYMENT_FAKE_GATEWAY_SECRET

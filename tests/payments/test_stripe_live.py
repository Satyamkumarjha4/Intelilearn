"""Unit under test: `payments.stripe_gateway.StripeGateway` against Stripe's real test mode (credits plan §13.4; phase
10.7). Run by hand with `make payments-live`; never part of `make check`, which needs no key and no network.

Why: the mocked tests prove we send what Stripe documents, but only Stripe can say the documentation, the pinned API
version and our request still agree. This is the early warning for a change on their side (a renamed parameter, a
version that is retired, a key that lost a permission), run against a throwaway session that is expired straight
afterwards. It makes no payment and never touches live mode.

Use cases:
- a real Checkout Session is created in test mode for an order, with the pinned API version, and comes back as a
  redirect to Stripe's own page, open for payment
- asking about it says it is still pending; once expired, Stripe says expired
- a refund for a payment that does not exist is refused as a rejection (so Stripe's error shape is the one we read)
- a key that is not a test-mode secret key skips everything, so these can never run against real money
"""

import os
import uuid

import pytest

from payments.config import GatewayConfig
from payments.errors import GatewayRejected
from payments.gateway import CheckoutOrder, CheckoutSession, PaymentStatus, ReturnUrls
from payments.stripe_gateway import StripeGateway

KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()

pytestmark = [
    pytest.mark.payments_live,
    pytest.mark.skipif(not KEY.startswith("sk_test_"), reason="needs STRIPE_SECRET_KEY set to a test-mode key"),
]

URLS = ReturnUrls(
    "http://localhost:3000/buy/return?order=live", "http://localhost:3000/buy/return?order=live&cancelled=1"
)


@pytest.fixture
def stripe():
    return StripeGateway(GatewayConfig({"secret_key": KEY, "webhook_secret": "whsec_unused"}))


def test_a_real_session_is_created_asked_about_and_expired(stripe):
    order = CheckoutOrder(str(uuid.uuid4()), 49900, "INR", "Socra live check (test mode)", "")

    session = stripe.create_checkout(order, URLS)
    try:
        assert session.kind == CheckoutSession.REDIRECT and session.provider_ref.startswith("cs_test_")
        assert session.redirect_url.startswith("https://checkout.stripe.com/")
        assert stripe.fetch_status(session.provider_ref).state == PaymentStatus.PENDING
    finally:
        stripe.api.post(f"/v1/checkout/sessions/{session.provider_ref}/expire", {})

    assert stripe.fetch_status(session.provider_ref).state == PaymentStatus.EXPIRED


def test_a_refund_for_a_payment_that_does_not_exist_is_a_rejection(stripe):
    with pytest.raises(GatewayRejected) as caught:
        stripe.refund("pi_does_not_exist", 100)

    assert "did not accept the key" not in str(
        caught.value
    )  # a refused key would be a rejection too, for the wrong reason

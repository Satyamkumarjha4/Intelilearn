"""Unit under test: `payments.razorpay_gateway.RazorpayGateway` against Razorpay's real test mode (credits plan §13.4;
phase 10.8). Run by hand with `make payments-live`; never part of `make check`, which needs no key and no network.

Why: the mocked tests prove we send what Razorpay documents, but only Razorpay can say the documentation and our request
still agree. This is the early warning for a change on their side (a renamed field, a key that lost a permission). It
makes no payment and never touches live mode; an order that is never paid costs nothing and is left for Razorpay to
age out.

Use cases:
- a real order is created in test mode for one of our orders (our id as its receipt) and comes back as a client checkout
  carrying the key id, Razorpay's order id and the amount
- asking about it says it is still pending
- a refund for a payment that does not exist is refused as a rejection (so Razorpay's error shape is the one we read)
- keys that are not test-mode keys skip everything, so these can never run against real money
"""

import os
import uuid

import pytest

from payments.config import GatewayConfig
from payments.errors import GatewayRejected
from payments.gateway import CheckoutOrder, CheckoutSession, PaymentStatus, ReturnUrls
from payments.razorpay_gateway import RazorpayGateway

KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()

pytestmark = [
    pytest.mark.payments_live,
    pytest.mark.skipif(
        not (KEY_ID.startswith("rzp_test_") and KEY_SECRET),
        reason="needs RAZORPAY_KEY_ID set to a test-mode key (rzp_test_...) and RAZORPAY_KEY_SECRET",
    ),
]

URLS = ReturnUrls("http://localhost:3000/buy/return?order=live", "http://localhost:3000/buy/return?order=live")


@pytest.fixture
def razorpay():
    config = {"key_id": KEY_ID, "key_secret": KEY_SECRET, "webhook_secret": "unused"}
    return RazorpayGateway(GatewayConfig(config))


def test_a_real_order_is_created_and_asked_about(razorpay):
    order = CheckoutOrder(str(uuid.uuid4()), 10000, "INR", "Socra live check (test mode)", "")

    session = razorpay.create_checkout(order, URLS)

    assert session.kind == CheckoutSession.CLIENT and session.adapter == "razorpay"
    assert session.provider_ref.startswith("order_")
    assert dict(session.client)["key"] == KEY_ID and dict(session.client)["amount"] == 10000
    assert razorpay.fetch_status(session.provider_ref).state == PaymentStatus.PENDING


def test_a_refund_for_a_payment_that_does_not_exist_is_a_rejection(razorpay):
    with pytest.raises(GatewayRejected) as caught:
        razorpay.refund("pay_doesnotexist0000", 100)

    assert "did not accept the keys" not in str(caught.value)  # a refused key is a rejection too, for the wrong reason

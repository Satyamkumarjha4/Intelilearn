"""Unit under test: `fetch_refund` of `StripeGateway` and `RazorpayGateway` over `httpx.MockTransport`, and the port's
default (credits plan D14; phase 10.9 step 0).

Why: the refund sweep needs one question answered the same way by every provider: is this refund still pending, done, or
failed? Each provider words it differently and the port must hide that. A gateway that cannot be asked must say so
rather than guess, and a refusal or an outage must be the port's errors.

Use cases:
- the port's default is `NotSupported`, and `can_fetch_refund` follows the declared capability
- Stripe: GET /v1/refunds/{id} with the pinned version; `succeeded` is processed, `pending` and `requires_action` are
  pending, `failed` and `canceled` are failed; the amount comes back in paise
- Razorpay: GET /v1/refunds/{id}; `processed`, `pending` and `failed` map as they say
- an unknown status is pending (never guessed done); a missing refund is rejected, an outage unavailable; the id in the
  path is escaped; no key is in a message
"""

import httpx
import pytest
from support.clock import FakeClock
from support.stripe import Wire

from payments.config import GatewayConfig
from payments.errors import GatewayRejected, GatewayUnavailable, NotSupported
from payments.gateway import PaymentGateway
from payments.razorpay_gateway import RazorpayGateway
from payments.stripe_gateway import StripeApi, StripeGateway

STRIPE_KEY, RZP_ID, RZP_SECRET = "sk_test_" + "k" * 24, "rzp_test_" + "i" * 14, "s" * 24


def stripe(wire):
    config = GatewayConfig({"secret_key": STRIPE_KEY, "webhook_secret": "whsec_x"})
    return StripeGateway(config, client=wire.client(), clock=FakeClock())


def razorpay(wire):
    config = GatewayConfig({"key_id": RZP_ID, "key_secret": RZP_SECRET, "webhook_secret": "x"})
    return RazorpayGateway(config, client=wire.client(), clock=FakeClock())


class TestThePort:
    def test_the_default_is_not_supported(self):
        class Plain(PaymentGateway):
            key, display_name = "plain", "Plain"

            def create_checkout(self, order, urls): ...
            def verify_webhook(self, headers, raw_body): ...
            def fetch_status(self, provider_ref): ...

        assert not Plain().can_fetch_refund
        with pytest.raises(NotSupported):
            Plain().fetch_refund("r1")

    def test_both_providers_declare_it(self):
        assert StripeGateway().can_fetch_refund and RazorpayGateway().can_fetch_refund


class TestStripe:
    def ask(self, status, amount=4000, ref="re_1"):
        wire = Wire((200, {"id": ref, "object": "refund", "amount": amount, "currency": "inr", "status": status}))
        return stripe(wire).fetch_refund(ref), wire

    def test_it_gets_the_refund_with_the_pinned_version(self):
        _, wire = self.ask("succeeded")

        assert (wire.sent.method, str(wire.sent.url)) == ("GET", "https://api.stripe.com/v1/refunds/re_1")
        assert wire.sent.headers["stripe-version"] == StripeApi.API_VERSION

    @pytest.mark.parametrize(
        ("said", "state"),
        [
            ("succeeded", "processed"), ("pending", "pending"), ("requires_action", "pending"),
            ("failed", "failed"), ("canceled", "failed"), ("something_new", "pending"),
        ],
    )  # fmt: skip
    def test_the_statuses_map(self, said, state):
        status, _ = self.ask(said)

        assert (status.state, status.amount_paise) == (state, 4000)

    def test_the_id_is_escaped(self):
        _, wire = self.ask("succeeded", ref="re/../x")

        assert wire.sent.url.raw_path == b"/v1/refunds/re%2F..%2Fx"

    def test_a_missing_refund_is_rejected_and_an_outage_unavailable(self):
        with pytest.raises(GatewayRejected):
            stripe(Wire((404, {"error": {"type": "invalid_request_error", "code": "resource_missing"}}))).fetch_refund(
                "x"
            )
        with pytest.raises(GatewayUnavailable):
            stripe(Wire(httpx.ConnectError("down"))).fetch_refund("re_1")

    def test_an_answer_without_a_status_is_unavailable(self):
        with pytest.raises(GatewayUnavailable):
            stripe(Wire((200, {"id": "re_1"}))).fetch_refund("re_1")


class TestRazorpay:
    def ask(self, status, amount=4000, ref="rfnd_1"):
        wire = Wire((200, {"id": ref, "entity": "refund", "amount": amount, "currency": "INR", "status": status}))
        return razorpay(wire).fetch_refund(ref), wire

    def test_it_gets_the_refund_with_basic_auth(self):
        _, wire = self.ask("processed")

        assert (wire.sent.method, str(wire.sent.url)) == ("GET", "https://api.razorpay.com/v1/refunds/rfnd_1")
        assert wire.sent.headers["authorization"].startswith("Basic ")

    @pytest.mark.parametrize(
        ("said", "state"),
        [("processed", "processed"), ("pending", "pending"), ("failed", "failed"), ("new", "pending")],
    )
    def test_the_statuses_map(self, said, state):
        status, _ = self.ask(said)

        assert (status.state, status.amount_paise) == (state, 4000)

    def test_a_missing_refund_is_rejected_and_an_outage_unavailable(self):
        with pytest.raises(GatewayRejected):
            razorpay(
                Wire((400, {"error": {"code": "BAD_REQUEST_ERROR", "description": "no such refund"}}))
            ).fetch_refund("x")
        with pytest.raises(GatewayUnavailable):
            razorpay(Wire((503, "down"))).fetch_refund("rfnd_1")

    def test_no_message_holds_a_key(self):
        quoting = {"error": {"code": "BAD_REQUEST_ERROR", "description": f"bad {RZP_SECRET} {RZP_ID}"}}

        with pytest.raises(GatewayRejected) as caught:
            razorpay(Wire((400, quoting))).fetch_refund("x")

        assert RZP_SECRET not in str(caught.value) and RZP_ID not in str(caught.value)

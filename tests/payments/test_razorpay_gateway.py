"""Unit under test: `payments.razorpay_gateway.RazorpayGateway` and `RazorpayApi`, its HTTPS client (credits plan §6.4,
T21, D19, D20; phase 10.8), over `httpx.MockTransport` with bodies shaped as Razorpay documents them.

Why: Razorpay is the way in if Stripe's India onboarding does not come through (D20), so the adapter has to be as good
as Stripe's, with no SDK. The amount must be paise, our order id must travel to Razorpay and back (as the receipt and in
the notes), the browser must be handed only what is public (the key id, never the secret), and every failure Razorpay
can return must become one of the port's errors without a key in any message.

Use cases:
- create_checkout: a JSON POST to /v1/orders with Basic auth (key id and secret), the order's paise and currency, our
  order id as the receipt (within Razorpay's 40 characters) and in the notes; the answer is a client checkout for the
  `razorpay` adapter carrying only the key id, the Razorpay order id, the amount, the currency, a display name, the
  description, the buyer's email as a prefill and "no retry" (a failed attempt is final, so `payment.failed` can end our
  order); the secret is nowhere in it
- no API version header is sent (Razorpay is versioned by path)
- create_checkout failures: no connection or a timeout, a 5xx, a 429 and a 409 are `GatewayUnavailable`; a 400 (which is
  also how a bad key is answered), a 401, a 403 and a 404 are `GatewayRejected` (also an unavailable); an answer without
  an order id is unavailable; nothing in a message holds a key
- fetch_status: GET of the order; `paid` when the order is paid (with the amount paid, the currency and the id of the
  payment that was taken, found from the order's payments), `pending` while it is created or attempted (a failed attempt
  does not end an order, so it is never `failed` or `expired` from here)
- refund: POST /v1/payments/{id}/refund for the amount in paise, with the idempotency key as `X-Refund-Idempotency` when
  there is one; a refund Razorpay says failed, an over-refund (400) and an outage are errors
- the gateway declares the refund capability, names its three settings, and is not switched on without all three
- the registry knows it when the adapters are loaded
"""

from datetime import UTC, datetime
from urllib.parse import quote

import httpx
import pytest
from support.clock import FakeClock
from support.stripe import Wire

from payments.config import GatewayConfig
from payments.errors import GatewayRejected, GatewayUnavailable
from payments.gateway import CheckoutOrder, CheckoutSession, PaymentGateway, PaymentStatus, ReturnUrls
from payments.razorpay_gateway import RazorpayApi, RazorpayGateway
from payments.registry import PaymentGateways

KEY_ID, KEY_SECRET, HOOK_SECRET = "rzp_test_" + "i" * 14, "s" * 24, "h" * 20  # not real keys
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
ORDER = CheckoutOrder("0b9c1c0e-aaaa-bbbb-cccc-000000000001", 49900, "INR", "Weekly Pro", "learner@example.com")
URLS = ReturnUrls("http://shop.test/buy/return?order=o1", "http://shop.test/buy/return?order=o1&cancelled=1")

RZP_ORDER = {  # an Order as the API returns it (api/orders/create)
    "id": "order_RB58MiP5SPFYyM", "entity": "order", "amount": 49900, "amount_paid": 0, "amount_due": 49900,
    "currency": "INR", "receipt": ORDER.order_id, "offer_id": None, "status": "created", "attempts": 0,
    "notes": {"order_id": ORDER.order_id}, "created_at": 1756455561,
}  # fmt: skip
PAYMENT = {  # a Payment (api/payments/fetch-with-id)
    "id": "pay_N8FUmetkCE2hZP", "entity": "payment", "amount": 49900, "currency": "INR", "status": "captured",
    "order_id": RZP_ORDER["id"], "captured": True, "method": "upi", "amount_refunded": 0, "refund_status": None,
    "error_code": None, "created_at": 1756455600,
}  # fmt: skip


def gateway(wire: Wire, **config) -> RazorpayGateway:
    values = {"key_id": KEY_ID, "key_secret": KEY_SECRET, "webhook_secret": HOOK_SECRET, **config}
    return RazorpayGateway(GatewayConfig(values), client=wire.client(), clock=FakeClock(NOW))


def error_body(description="Nope.", code="BAD_REQUEST_ERROR", field=None):
    return {
        "error": {
            "code": code, "description": description, "source": "business", "step": "payment_initiation",
            "reason": "input_validation_failed", "metadata": {}, "field": field,
        }
    }  # fmt: skip


def body_of(wire: Wire):
    import json

    return json.loads(wire.sent.content)


class TestCreatingACheckout:
    def test_it_posts_a_json_order_for_the_paise_with_basic_auth(self):
        wire = Wire((200, RZP_ORDER))

        gateway(wire).create_checkout(ORDER, URLS)

        assert (wire.sent.method, str(wire.sent.url)) == ("POST", "https://api.razorpay.com/v1/orders")
        assert wire.sent.headers["content-type"] == "application/json"
        assert wire.sent.headers["authorization"].startswith("Basic ")
        body = body_of(wire)
        assert (body["amount"], body["currency"]) == (49900, "INR")

    def test_basic_auth_is_the_key_id_and_the_secret(self):
        import base64

        wire = Wire((200, RZP_ORDER))

        gateway(wire).create_checkout(ORDER, URLS)

        token = wire.sent.headers["authorization"].split(" ", 1)[1]
        assert base64.b64decode(token).decode() == f"{KEY_ID}:{KEY_SECRET}"

    def test_our_order_id_is_the_receipt_and_in_the_notes(self):
        wire = Wire((200, RZP_ORDER))

        gateway(wire).create_checkout(ORDER, URLS)

        body = body_of(wire)
        assert body["receipt"] == ORDER.order_id and len(body["receipt"]) <= 40
        assert body["notes"] == {"order_id": ORDER.order_id}

    def test_a_receipt_is_never_longer_than_razorpay_allows(self):
        wire = Wire((200, RZP_ORDER))

        gateway(wire).create_checkout(CheckoutOrder("x" * 80, 5000, "INR", "Pro", ""), URLS)

        assert len(body_of(wire)["receipt"]) == 40

    def test_no_api_version_header_is_sent(self):
        wire = Wire((200, RZP_ORDER))

        gateway(wire).create_checkout(ORDER, URLS)

        assert not [h for h in wire.sent.headers if "version" in h.lower()]

    def test_the_answer_is_a_client_checkout_with_only_public_parameters(self):
        session = gateway(Wire((200, RZP_ORDER))).create_checkout(ORDER, URLS)

        assert (session.kind, session.provider_ref, session.adapter) == (
            CheckoutSession.CLIENT, RZP_ORDER["id"], "razorpay",
        )  # fmt: skip
        assert dict(session.client) == {
            "key": KEY_ID, "order_id": RZP_ORDER["id"], "amount": 49900, "currency": "INR", "name": "Socra",
            "description": "Weekly Pro", "prefill": {"email": "learner@example.com"}, "retry": {"enabled": False},
        }  # fmt: skip
        assert KEY_SECRET not in str(session.as_json()) and HOOK_SECRET not in str(session.as_json())

    def test_the_session_json_the_browser_gets_names_the_adapter(self):
        session = gateway(Wire((200, RZP_ORDER))).create_checkout(ORDER, URLS)

        assert session.as_json()["kind"] == "client" and session.as_json()["adapter"] == "razorpay"

    def test_no_prefill_is_sent_without_an_email(self):
        session = gateway(Wire((200, RZP_ORDER))).create_checkout(CheckoutOrder("o1", 5000, "INR", "Pro", ""), URLS)

        assert "prefill" not in session.client


class TestWhenRazorpayFails:
    @pytest.mark.parametrize(
        "answer",
        [
            httpx.ConnectError("no route"),
            httpx.ReadTimeout("slow"),
            (500, error_body(code="SERVER_ERROR")),
            (502, "<html>bad gateway</html>"),
            (429, error_body(code="BAD_REQUEST_ERROR")),
            (409, error_body("Another request with the same idempotency key is still in progress.")),
        ],
    )
    def test_an_outage_or_a_busy_razorpay_is_unavailable(self, answer):
        with pytest.raises(GatewayUnavailable) as caught:
            gateway(Wire(answer)).create_checkout(ORDER, URLS)

        assert not isinstance(caught.value, GatewayRejected)

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_a_refusal_is_rejected(self, status):
        with pytest.raises(GatewayRejected):
            gateway(Wire((status, error_body()))).create_checkout(ORDER, URLS)

    def test_a_rejection_is_still_an_unavailable_checkout(self):
        with pytest.raises(GatewayUnavailable):
            gateway(Wire((400, error_body()))).create_checkout(ORDER, URLS)

    @pytest.mark.parametrize("body", [{}, {"id": 5}, {"entity": "order"}, [], "oops"])
    def test_an_answer_without_an_order_id_is_unavailable(self, body):
        with pytest.raises(GatewayUnavailable):
            gateway(Wire((200, body))).create_checkout(ORDER, URLS)

    def test_no_message_holds_a_key(self):
        quoting = error_body(description=f"Authentication failed for {KEY_ID} with {KEY_SECRET}")
        answers = (httpx.ConnectError(f"cannot reach with {KEY_SECRET}"), (400, quoting), (401, quoting))
        for answer in answers:
            with pytest.raises(GatewayUnavailable) as caught:
                gateway(Wire(answer)).create_checkout(ORDER, URLS)
            assert KEY_SECRET not in str(caught.value) and KEY_ID not in str(caught.value)
            assert KEY_SECRET not in repr(caught.value)

    def test_razorpays_description_is_kept_for_staff(self):
        with pytest.raises(GatewayRejected, match="The amount must be at least INR 1.00"):
            gateway(Wire((400, error_body("The amount must be at least INR 1.00", field="amount")))).create_checkout(
                ORDER, URLS
            )

    def test_a_refused_key_says_which_settings_to_check(self):
        with pytest.raises(GatewayRejected, match="RAZORPAY_KEY_ID") as caught:
            gateway(Wire((401, error_body("Authentication failed")))).create_checkout(ORDER, URLS)

        assert "HTTP 401" in str(caught.value)

    def test_the_gateways_config_never_shows_a_key(self):
        shown = repr(gateway(Wire((200, RZP_ORDER))).config)

        assert KEY_SECRET not in shown and KEY_ID not in shown and HOOK_SECRET not in shown


class TestAskingAboutAnOrder:
    def ask(self, *answers, ref="order_RB58MiP5SPFYyM"):
        wire = Wire(*answers)
        return gateway(wire).fetch_status(ref), wire

    def test_it_gets_the_order(self):
        _, wire = self.ask((200, RZP_ORDER))

        first = wire.requests[0]
        assert (first.method, str(first.url)) == ("GET", "https://api.razorpay.com/v1/orders/order_RB58MiP5SPFYyM")
        assert first.headers["authorization"].startswith("Basic ")

    @pytest.mark.parametrize("state", ["created", "attempted"])
    def test_an_order_not_yet_paid_is_pending_and_asks_nothing_more(self, state):
        status, wire = self.ask((200, {**RZP_ORDER, "status": state}))

        assert status.state == PaymentStatus.PENDING and len(wire.requests) == 1

    def test_a_paid_order_is_paid_with_the_payment_that_was_taken(self):
        paid = {**RZP_ORDER, "status": "paid", "amount_paid": 49900, "amount_due": 0}
        failed = {**PAYMENT, "id": "pay_FAILED", "status": "failed", "captured": False}
        payments = {"entity": "collection", "count": 2, "items": [failed, PAYMENT]}

        status, wire = self.ask((200, paid), (200, payments))

        assert status == PaymentStatus(PaymentStatus.PAID, 49900, "INR", "pay_N8FUmetkCE2hZP")
        assert str(wire.sent.url) == "https://api.razorpay.com/v1/orders/order_RB58MiP5SPFYyM/payments"

    def test_a_payment_since_refunded_is_still_the_one_that_was_taken(self):
        paid = {**RZP_ORDER, "status": "paid", "amount_paid": 49900}
        refunded = {**PAYMENT, "status": "refunded", "amount_refunded": 49900, "refund_status": "full"}

        status, _ = self.ask((200, paid), (200, {"entity": "collection", "count": 1, "items": [refunded]}))

        assert status.payment_ref == PAYMENT["id"]

    def test_a_paid_order_whose_payment_cannot_be_found_is_paid_without_a_reference(self):
        paid = {**RZP_ORDER, "status": "paid", "amount_paid": 49900}

        status, _ = self.ask((200, paid), (200, {"entity": "collection", "count": 0, "items": []}))

        assert (status.state, status.payment_ref) == (PaymentStatus.PAID, "")

    def test_the_id_in_the_path_is_escaped(self):
        _, wire = self.ask((200, RZP_ORDER), ref="order/../../payments?x=1")

        assert wire.requests[0].url.raw_path == f"/v1/orders/{quote('order/../../payments?x=1', safe='')}".encode()

    def test_a_missing_order_is_rejected_and_an_outage_unavailable(self):
        with pytest.raises(GatewayRejected):
            gateway(Wire((400, error_body("The id provided does not exist")))).fetch_status("order_gone")
        with pytest.raises(GatewayUnavailable):
            gateway(Wire((503, error_body(code="SERVER_ERROR")))).fetch_status("order_x")


class TestRefunding:
    REFUND = {  # api/refunds/create-normal
        "id": "rfnd_FP8QHiV938haTz", "entity": "refund", "amount": 49900, "currency": "INR",
        "payment_id": "pay_N8FUmetkCE2hZP", "notes": [], "receipt": None, "acquirer_data": {"arn": None},
        "created_at": 1597078866, "batch_id": None, "status": "processed", "speed_processed": "normal",
    }  # fmt: skip

    def test_it_refunds_the_payment_for_the_amount_in_paise(self):
        wire = Wire((200, self.REFUND))

        result = gateway(wire).refund("pay_N8FUmetkCE2hZP", 49900)

        assert (wire.sent.method, str(wire.sent.url)) == (
            "POST", "https://api.razorpay.com/v1/payments/pay_N8FUmetkCE2hZP/refund",
        )  # fmt: skip
        assert body_of(wire) == {"amount": 49900}
        assert "x-refund-idempotency" not in wire.sent.headers
        assert (result.refund_ref, result.amount_paise) == ("rfnd_FP8QHiV938haTz", 49900)

    def test_a_key_is_sent_as_the_refund_idempotency_header(self):
        wire = Wire((200, self.REFUND))

        gateway(wire).refund_with_key("pay_1", 49900, "refund-0b9c1c0e-aaaa-bbbb-cccc-000000000001")

        assert wire.sent.headers["x-refund-idempotency"] == "refund-0b9c1c0e-aaaa-bbbb-cccc-000000000001"
        assert body_of(wire) == {"amount": 49900}

    def test_a_pending_refund_is_accepted(self):
        result = gateway(Wire((200, {**self.REFUND, "status": "pending"}))).refund("pay_1", 49900)

        assert result.refund_ref == "rfnd_FP8QHiV938haTz"

    def test_a_refund_razorpay_says_failed_is_an_error(self):
        with pytest.raises(GatewayRejected):
            gateway(Wire((200, {**self.REFUND, "status": "failed"}))).refund("pay_1", 49900)

    def test_refunding_more_than_was_taken_is_rejected_with_razorpays_words(self):
        too_much = error_body("The refund amount provided is greater than amount captured.", field="amount")

        with pytest.raises(GatewayRejected, match="greater than amount captured"):
            gateway(Wire((400, too_much))).refund("pay_1", 60000)

    def test_a_reused_key_still_in_flight_is_unavailable_not_rejected(self):
        busy = error_body("Another request with the same idempotency key is still in progress.")

        with pytest.raises(GatewayUnavailable) as caught:
            gateway(Wire((409, busy))).refund_with_key("pay_1", 100, "refund-1234567890")

        assert not isinstance(caught.value, GatewayRejected)

    def test_an_outage_is_unavailable(self):
        with pytest.raises(GatewayUnavailable):
            gateway(Wire(httpx.ConnectError("down"))).refund("pay_1", 100)

    def test_a_missing_payment_reference_is_refused_before_anything_is_sent(self):
        wire = Wire((200, self.REFUND))

        with pytest.raises(GatewayRejected):
            gateway(wire).refund("", 100)

        assert wire.requests == []

    def test_the_payment_id_in_the_path_is_escaped(self):
        wire = Wire((200, self.REFUND))

        gateway(wire).refund("pay/../x", 100)

        assert wire.sent.url.raw_path == b"/v1/payments/pay%2F..%2Fx/refund"


class TestTheGateway:
    def test_it_declares_the_refund_capability_and_in_rupees_only(self):
        assert RazorpayGateway().can_refund and RazorpayGateway.supported_currencies == ("INR",)
        assert (RazorpayGateway.key, RazorpayGateway.display_name) == ("razorpay", "Razorpay")

    def test_it_reads_its_three_settings(self):
        assert RazorpayGateway.config_names() == {
            "key_id": "RAZORPAY_KEY_ID",
            "key_secret": "RAZORPAY_KEY_SECRET",
            "webhook_secret": "RAZORPAY_WEBHOOK_SECRET",
        }  # fmt: skip

    def test_it_is_not_switched_on_without_all_three(self):
        full = {"key_id": KEY_ID, "key_secret": KEY_SECRET, "webhook_secret": HOOK_SECRET}
        for name in full:
            partial = {k: v for k, v in full.items() if k != name}
            assert RazorpayGateway(GatewayConfig(partial)).missing_config() == [name]
        assert RazorpayGateway(GatewayConfig(full)).missing_config() == []

    def test_it_is_a_payment_gateway_the_registry_knows(self):
        assert issubclass(RazorpayGateway, PaymentGateway)
        assert PaymentGateways.REGISTERED["razorpay"] is RazorpayGateway

    def test_it_is_built_from_the_settings(self, settings):
        settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET = KEY_ID, KEY_SECRET
        settings.RAZORPAY_WEBHOOK_SECRET = HOOK_SECRET

        built = RazorpayGateway.from_settings()

        assert built.missing_config() == [] and built.config.get("key_id") == KEY_ID

    def test_the_api_has_no_version_to_pin(self):
        assert not hasattr(RazorpayApi, "API_VERSION")

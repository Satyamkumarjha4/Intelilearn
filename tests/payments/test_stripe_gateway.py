"""Unit under test: `payments.stripe_gateway.StripeGateway` and `StripeApi`, its HTTPS client (credits plan §6.4, T21,
D19; phase 10.7), over `httpx.MockTransport` with bodies shaped as Stripe documents them.

Why: Stripe is where the money moves, and an SDK is deliberately not used (T21), so the request shape is ours to get
right: an amount in paise, not rupees; our order id carried to Stripe and back; an idempotency key so a retried request
cannot make a second Checkout Session; a pinned API version so Stripe's response shapes cannot change under us. Every
failure Stripe can return must become one of the port's errors, and a key must never reach a log or a message.

Use cases:
- create_checkout: a POST to /v1/checkout/sessions, form encoded, `mode=payment`, one INR line item whose amount is the
  order's paise, the order id as `client_reference_id` and in the session's and the payment's metadata, the return URLs,
  an expiry between Stripe's 30 minutes and 24 hours, the buyer's email when there is one; the answer is a redirect
- every request carries the pinned `Stripe-Version`, the secret key as Basic auth and, for a POST that creates, an
  `Idempotency-Key` of the order id
- create_checkout failures: no connection or a timeout, a 5xx, a 429 and a 409 are `GatewayUnavailable`; a 401, a 403
  and a 400 are `GatewayRejected` (also an unavailable); a refused key is told by Stripe's code (`api_key_expired`), not
  its message; an answer without a session id or link is unavailable; nothing in a message holds the key
- fetch_status: GET of the session; `paid` when its payment_status is paid (with the amount, the currency in capitals
  and the payment intent as the payment reference), `expired` when its status is expired, `pending` while it is open or
  complete but not yet paid; the id in the path is escaped
- refund: POST /v1/refunds for the payment intent and the amount in paise; the answer's id and amount; a refund that
  Stripe says failed, an over-refund (400) and an outage are errors
- the gateway declares the refund capability, names its two settings, and is not switched on without both
- the registry knows it when the adapters are loaded
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from support.clock import FakeClock
from support.stripe import Wire

from payments.config import GatewayConfig
from payments.errors import GatewayRejected, GatewayUnavailable
from payments.gateway import CheckoutOrder, CheckoutSession, PaymentGateway, PaymentStatus, ReturnUrls
from payments.registry import PaymentGateways
from payments.stripe_gateway import StripeApi, StripeGateway

KEY = "sk_test_" + "k" * 24  # not a real key
SECRET = "whsec_" + "w" * 24
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
ORDER = CheckoutOrder("0b9c1c0e-aaaa-bbbb-cccc-000000000001", 49900, "INR", "Weekly Pro", "learner@example.com")
URLS = ReturnUrls("http://shop.test/buy/return?order=o1", "http://shop.test/buy/return?order=o1&cancelled=1")

SESSION = {  # a Checkout Session as the API returns it (api/checkout/sessions/object)
    "id": "cs_test_a11YYufWQzNY63zpQ6QSNRQhkUpVph4WRmzW0zWJO2znZKdVujZ0N0S22u",
    "object": "checkout.session",
    "amount_subtotal": 49900,
    "amount_total": 49900,
    "client_reference_id": ORDER.order_id,
    "currency": "inr",
    "expires_at": int((NOW + timedelta(hours=23)).timestamp()),
    "livemode": False,
    "metadata": {"order_id": ORDER.order_id},
    "mode": "payment",
    "payment_intent": None,
    "payment_status": "unpaid",
    "status": "open",
    "url": "https://checkout.stripe.com/c/pay/cs_test_a11YYufWQzNY63zpQ6QSNRQhkUpVph4WRmzW0zWJO2znZKdVujZ0N0S22u#frag",
}


def gateway(wire: Wire, **config) -> StripeGateway:
    values = {"secret_key": KEY, "webhook_secret": SECRET, **config}
    return StripeGateway(GatewayConfig(values), client=wire.client(), clock=FakeClock(NOW))


def error_body(kind="invalid_request_error", message="Nope.", code=None):
    return {"error": {"type": kind, "message": message, **({"code": code} if code else {})}}


class TestCreatingACheckout:
    def test_it_posts_one_inr_payment_line_for_the_orders_paise(self):
        wire = Wire((200, SESSION))

        gateway(wire).create_checkout(ORDER, URLS)

        assert (wire.sent.method, str(wire.sent.url)) == ("POST", "https://api.stripe.com/v1/checkout/sessions")
        assert wire.sent.headers["content-type"] == "application/x-www-form-urlencoded"
        form = wire.form()
        assert form["mode"] == "payment"
        assert form["line_items[0][quantity]"] == "1"
        assert form["line_items[0][price_data][currency]"] == "inr"
        assert form["line_items[0][price_data][unit_amount]"] == "49900"
        assert form["line_items[0][price_data][product_data][name]"] == "Weekly Pro"

    def test_it_carries_our_order_id_to_stripe_and_back(self):
        wire = Wire((200, SESSION))

        gateway(wire).create_checkout(ORDER, URLS)

        form = wire.form()
        assert form["client_reference_id"] == ORDER.order_id
        assert form["metadata[order_id]"] == ORDER.order_id
        assert form["payment_intent_data[metadata][order_id]"] == ORDER.order_id

    def test_the_return_urls_and_the_buyers_email_are_sent(self):
        wire = Wire((200, SESSION))

        gateway(wire).create_checkout(ORDER, URLS)

        form = wire.form()
        assert (form["success_url"], form["cancel_url"]) == (URLS.success, URLS.cancel)
        assert form["customer_email"] == "learner@example.com"

    def test_no_email_is_sent_when_there_is_none(self):
        wire = Wire((200, SESSION))

        gateway(wire).create_checkout(CheckoutOrder("o1", 5000, "INR", "Pro", ""), URLS)

        assert "customer_email" not in wire.form()

    def test_it_asks_for_an_expiry_inside_stripes_window(self):
        wire = Wire((200, SESSION))

        gateway(wire).create_checkout(ORDER, URLS)

        asked = datetime.fromtimestamp(int(wire.form()["expires_at"]), UTC)
        assert timedelta(minutes=30) < asked - NOW < timedelta(hours=24)

    def test_every_request_has_the_pinned_version_the_key_and_the_order_as_its_idempotency_key(self):
        wire = Wire((200, SESSION))

        gateway(wire).create_checkout(ORDER, URLS)

        assert wire.sent.headers["stripe-version"] == StripeApi.API_VERSION == "2026-10-28.endive"
        assert wire.sent.headers["idempotency-key"] == ORDER.order_id
        assert wire.sent.headers["authorization"].startswith("Basic ")

    def test_the_answer_is_a_redirect_to_stripes_page(self):
        session = gateway(Wire((200, SESSION))).create_checkout(ORDER, URLS)

        assert (session.kind, session.provider_ref, session.redirect_url) == (
            CheckoutSession.REDIRECT,
            SESSION["id"],
            SESSION["url"],
        )
        assert session.expires_at == datetime.fromtimestamp(SESSION["expires_at"], UTC)
        assert session.as_json() == {"kind": "redirect", "redirect_url": SESSION["url"]}


class TestWhenStripeFails:
    @pytest.mark.parametrize(
        "answer",
        [
            httpx.ConnectError("no route"),
            httpx.ReadTimeout("slow"),
            (500, error_body("api_error")),
            (502, "<html>bad gateway</html>"),
            (429, error_body(code="rate_limit")),
            (409, error_body("idempotency_error")),
        ],
    )
    def test_an_outage_or_a_busy_stripe_is_unavailable(self, answer):
        with pytest.raises(GatewayUnavailable) as caught:
            gateway(Wire(answer)).create_checkout(ORDER, URLS)

        assert not isinstance(caught.value, GatewayRejected)

    @pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
    def test_a_refusal_is_rejected(self, status):
        with pytest.raises(GatewayRejected):
            gateway(Wire((status, error_body()))).create_checkout(ORDER, URLS)

    def test_a_rejection_is_still_an_unavailable_checkout(self):
        with pytest.raises(GatewayUnavailable):
            gateway(Wire((400, error_body()))).create_checkout(ORDER, URLS)

    @pytest.mark.parametrize("body", [{}, {"id": "cs_test_1"}, {"url": "https://x"}, [], "oops"])
    def test_an_answer_without_a_session_and_a_link_is_unavailable(self, body):
        with pytest.raises(GatewayUnavailable):
            gateway(Wire((200, body))).create_checkout(ORDER, URLS)

    def test_no_message_holds_the_key(self):
        wrong_key = error_body(message=f"Invalid API Key provided: {KEY}")
        for answer in (httpx.ConnectError(f"cannot reach with {KEY}"), (401, wrong_key), (400, wrong_key)):
            with pytest.raises(GatewayUnavailable) as caught:
                gateway(Wire(answer)).create_checkout(ORDER, URLS)
            assert KEY not in str(caught.value) and KEY not in repr(caught.value)

    def test_a_refused_key_says_why_by_stripes_code_and_never_by_its_message(self):
        expired = error_body("api_error", message=f"Expired API Key provided: {KEY[:12]}***", code="api_key_expired")

        with pytest.raises(GatewayRejected, match="HTTP 401, api_key_expired") as caught:
            gateway(Wire((401, expired))).create_checkout(ORDER, URLS)

        assert "Expired API Key provided" not in str(caught.value) and KEY[:12] not in str(caught.value)

    def test_a_stripe_message_a_staff_member_can_use_is_kept_for_a_400(self):
        with pytest.raises(GatewayRejected, match="Amount must be at least 50 paise"):
            gateway(Wire((400, error_body(message="Amount must be at least 50 paise.")))).create_checkout(ORDER, URLS)

    def test_the_gateways_config_never_shows_the_key(self):
        assert KEY not in repr(gateway(Wire((200, SESSION))).config)


class TestAskingAboutASession:
    def ask(self, session, ref="cs_test_1"):
        wire = Wire((200, session))
        return gateway(wire).fetch_status(ref), wire

    def test_it_gets_the_session_with_the_pinned_version(self):
        _, wire = self.ask(SESSION)

        assert (wire.sent.method, str(wire.sent.url)) == (
            "GET",
            "https://api.stripe.com/v1/checkout/sessions/cs_test_1",
        )
        assert wire.sent.headers["stripe-version"] == StripeApi.API_VERSION
        assert "idempotency-key" not in wire.sent.headers

    def test_a_paid_session_is_paid_with_its_amount_and_payment(self):
        status, _ = self.ask({**SESSION, "status": "complete", "payment_status": "paid", "payment_intent": "pi_3Abc"})

        assert status == PaymentStatus(PaymentStatus.PAID, 49900, "INR", "pi_3Abc")

    def test_an_open_session_is_pending(self):
        status, _ = self.ask(SESSION)

        assert status.state == PaymentStatus.PENDING

    def test_a_complete_session_that_is_not_yet_paid_is_pending(self):
        status, _ = self.ask({**SESSION, "status": "complete", "payment_status": "unpaid", "payment_intent": "pi_1"})

        assert status.state == PaymentStatus.PENDING

    def test_an_expired_session_is_expired(self):
        status, _ = self.ask({**SESSION, "status": "expired", "url": None})

        assert status.state == PaymentStatus.EXPIRED

    def test_the_id_in_the_path_is_escaped(self):
        _, wire = self.ask(SESSION, ref="cs/../../refunds?x=1")

        assert wire.sent.url.raw_path == b"/v1/checkout/sessions/cs%2F..%2F..%2Frefunds%3Fx%3D1"

    def test_a_missing_session_is_rejected_and_an_outage_unavailable(self):
        with pytest.raises(GatewayRejected):
            gateway(Wire((404, error_body(code="resource_missing")))).fetch_status("cs_gone")
        with pytest.raises(GatewayUnavailable):
            gateway(Wire((503, error_body("api_error")))).fetch_status("cs_test_1")


class TestRefunding:
    REFUND = {  # api/refunds/object
        "id": "re_1Nispe2eZvKYlo2Cd31jOCgZ",
        "object": "refund",
        "amount": 49900,
        "charge": "ch_1",
        "currency": "inr",
        "payment_intent": "pi_3Abc",
        "reason": None,
        "status": "succeeded",
    }

    def test_it_refunds_the_payment_intent_for_the_amount_in_paise(self):
        wire = Wire((200, self.REFUND))

        result = gateway(wire).refund("pi_3Abc", 49900)

        assert (wire.sent.method, str(wire.sent.url)) == ("POST", "https://api.stripe.com/v1/refunds")
        assert wire.form() == {"payment_intent": "pi_3Abc", "amount": "49900"}
        assert wire.sent.headers["stripe-version"] == StripeApi.API_VERSION
        assert (result.refund_ref, result.amount_paise) == ("re_1Nispe2eZvKYlo2Cd31jOCgZ", 49900)

    def test_a_refund_that_is_still_pending_is_accepted(self):
        result = gateway(Wire((200, {**self.REFUND, "status": "pending"}))).refund("pi_3Abc", 49900)

        assert result.amount_paise == 49900

    @pytest.mark.parametrize("state", ["failed", "canceled"])
    def test_a_refund_stripe_says_failed_is_an_error(self, state):
        with pytest.raises(GatewayRejected):
            gateway(Wire((200, {**self.REFUND, "status": state}))).refund("pi_3Abc", 49900)

    def test_refunding_more_than_is_left_is_rejected_with_stripes_words(self):
        too_much = error_body(
            message="Refund amount (₹600.00) is greater than unrefunded amount on the charge (₹499.00)."
        )

        with pytest.raises(GatewayRejected, match="greater than unrefunded amount"):
            gateway(Wire((400, too_much))).refund("pi_3Abc", 60000)

    def test_an_outage_is_unavailable(self):
        with pytest.raises(GatewayUnavailable):
            gateway(Wire(httpx.ConnectError("down"))).refund("pi_3Abc", 100)

    def test_a_missing_payment_reference_is_refused_before_anything_is_sent(self):
        wire = Wire((200, self.REFUND))

        with pytest.raises(GatewayRejected):
            gateway(wire).refund("", 100)

        assert wire.requests == []


class TestTheGateway:
    def test_it_declares_the_refund_capability_and_in_rupees_only(self):
        gateway_ = StripeGateway()

        assert gateway_.can_refund and StripeGateway.supported_currencies == ("INR",)
        assert (StripeGateway.key, StripeGateway.display_name) == ("stripe", "Stripe")

    def test_it_reads_its_two_settings(self):
        assert StripeGateway.config_names() == {
            "secret_key": "STRIPE_SECRET_KEY",
            "webhook_secret": "STRIPE_WEBHOOK_SECRET",
        }

    def test_it_is_not_switched_on_without_both(self):
        assert StripeGateway(GatewayConfig({"secret_key": KEY})).missing_config() == ["webhook_secret"]
        assert StripeGateway(GatewayConfig({"webhook_secret": SECRET})).missing_config() == ["secret_key"]
        assert StripeGateway(GatewayConfig({"secret_key": KEY, "webhook_secret": SECRET})).missing_config() == []

    def test_it_is_a_payment_gateway_the_registry_knows(self):
        assert issubclass(StripeGateway, PaymentGateway)
        assert PaymentGateways.REGISTERED["stripe"] is StripeGateway

    def test_it_is_built_from_the_settings(self, settings):
        settings.STRIPE_SECRET_KEY, settings.STRIPE_WEBHOOK_SECRET = KEY, SECRET

        built = StripeGateway.from_settings()

        assert built.missing_config() == [] and built.config.get("secret_key") == KEY

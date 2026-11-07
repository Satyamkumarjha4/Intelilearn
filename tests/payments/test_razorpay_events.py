"""Unit under test: `payments.razorpay_events` (`RazorpaySignature`, `RazorpayEventReader`) and
`RazorpayGateway.verify_webhook` (credits plan §6.4, T23; phase 10.8), with events shaped as Razorpay documents them
(webhooks/payloads: order.paid, payment.failed, refund.processed, payment.dispute.created).

Why: a webhook is a stranger's HTTP request that moves money, so nothing in it counts until its signature is proved over
the raw bytes. Razorpay signs with no timestamp, so a captured request could be sent again at any time: replay is
stopped by the event id it sends in a header, which the order keeps once. Once proved, its events have to become the
four things the rest of the app understands, exactly once each. A refund is keyed by the refund (`refund.created` and
`refund.processed` are one refund), as Stripe's are, so it counts once.

Use cases:
- the signature: a header computed as the hex HMAC-SHA256 of the raw body with the webhook secret is accepted, also in
  capitals; a vector computed outside the code is accepted
- refused as `InvalidWebhook`: a wrong secret, the API key secret used by mistake, an altered body (even by a space), a
  missing, empty or non-hex header, an empty webhook secret
- `order.paid` is a success (the amount paid, the currency, Razorpay's order as the reference, the payment's id as the
  payment reference), keyed by the event id header; an order that is not paid says nothing; `payment.captured` and
  `payment.authorized`, which come beside it, say nothing, so a success is not counted twice
- `payment.failed` is a failure for the order the payment belongs to, keyed by the event id header
- a refund (`refund.created` or `refund.processed`, once it is processed) is a refunded event for that refund's own
  amount, found by its payment, under the id `refund:<refund id>` whichever of the two arrives; one that is pending or
  failed says nothing
- a dispute raised is a disputed event for its amount, found by its payment, keyed by the event id header; the other
  dispute events say nothing
- an event that needs the event id header and has none is refused
- events nobody here cares about are an empty list; an event of ours that is missing what it needs, or a body that is
  not JSON or not an event, is an `InvalidWebhook`
- the event's time is Razorpay's `created_at`
"""

import json
from datetime import UTC, datetime

import pytest
from support.clock import FakeClock
from support.razorpay import CREATED, envelope, order, payment, refund
from support.razorpay import sign as signed

from payments.config import GatewayConfig
from payments.errors import InvalidWebhook
from payments.gateway import PaymentEvent
from payments.razorpay_events import RazorpayEventReader, RazorpaySignature
from payments.razorpay_gateway import RazorpayGateway

SECRET, API_SECRET = "h" * 20, "s" * 24  # not real secrets
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def sign(body: bytes, secret: str = SECRET) -> str:
    return signed(body, secret)


def gateway(secret: str = SECRET) -> RazorpayGateway:
    config = GatewayConfig({"key_id": "rzp_test_x", "key_secret": API_SECRET, "webhook_secret": secret})
    return RazorpayGateway(config, clock=FakeClock(NOW))


def deliver(event: dict, *, event_id: str | None = "evt_1", secret: str = SECRET, body: bytes | None = None):
    raw = body if body is not None else json.dumps(event).encode()
    headers = {"X-Razorpay-Signature": sign(raw, secret)}
    if event_id is not None:
        headers["X-Razorpay-Event-Id"] = event_id
    return gateway().verify_webhook(headers, raw)


class TestTheSignature:
    BODY = b'{"event":"order.paid"}'

    def verify(self, header: str, body: bytes = BODY, secret: str = SECRET):
        RazorpaySignature().verify(header, body, secret)

    def test_a_computed_signature_is_accepted(self):
        self.verify(sign(self.BODY))

    def test_it_is_accepted_in_capitals(self):
        self.verify(sign(self.BODY).upper())

    def test_a_vector_computed_outside_the_code_is_accepted(self):
        self.verify(
            "efd02f3699133f51c4dbcda408e6d143b1bebc537a8ce243bddfd5345d58a229", secret="rzp_webhook_test_secret"
        )

    def test_a_wrong_secret_is_refused(self):
        with pytest.raises(InvalidWebhook):
            self.verify(sign(self.BODY, "another"))

    def test_the_api_key_secret_is_not_the_webhook_secret(self):
        with pytest.raises(InvalidWebhook):
            self.verify(sign(self.BODY, API_SECRET))

    @pytest.mark.parametrize("body", [b'{"event":"order.paid" }', b'{"event":"order.paid"}\n', b""])
    def test_an_altered_body_is_refused(self, body):
        header = sign(self.BODY)

        with pytest.raises(InvalidWebhook):
            self.verify(header, body=body)

    @pytest.mark.parametrize("header", ["", "   ", "not-hex-at-all", "abc", "z" * 64])
    def test_a_header_that_is_missing_or_unreadable_is_refused(self, header):
        with pytest.raises(InvalidWebhook):
            self.verify(header)

    def test_an_empty_secret_refuses_everything(self):
        with pytest.raises(InvalidWebhook):
            self.verify(sign(self.BODY, ""), secret="")

    def test_a_missing_header_is_refused_by_the_gateway(self):
        with pytest.raises(InvalidWebhook):
            gateway().verify_webhook({}, self.BODY)

    def test_the_gateway_finds_the_headers_whatever_their_case(self):
        raw = json.dumps(envelope("payment.captured", payment=payment())).encode()
        headers = {"x-razorpay-signature": sign(raw), "x-razorpay-event-id": "evt_9"}

        assert gateway().verify_webhook(headers, raw) == []

    def test_a_replayed_body_verifies_again_because_replay_is_stopped_by_the_event_id_not_here(self):
        raw = json.dumps(envelope("order.paid", order=order(), payment=payment())).encode()
        headers = {"X-Razorpay-Signature": sign(raw), "X-Razorpay-Event-Id": "evt_1"}

        first, again = gateway().verify_webhook(headers, raw), gateway().verify_webhook(headers, raw)

        assert first == again and first[0].event_id == "evt_1"


class TestPaymentsThatClearOrFail:
    def test_order_paid_is_a_success(self):
        (event,) = deliver(envelope("order.paid", order=order(), payment=payment()), event_id="evt_paid")

        assert event == PaymentEvent(
            event_id="evt_paid", kind="succeeded", provider_ref="order_DESlLckIVRkHWj", amount_paise=49900,
            currency="INR", occurred_at=datetime.fromtimestamp(CREATED, UTC), payment_ref="pay_DESlfW9H8K9uqM",
        )  # fmt: skip

    def test_the_amount_is_what_was_paid_so_a_short_payment_is_seen_as_a_mismatch(self):
        (event,) = deliver(envelope("order.paid", order=order(amount_paid=100, amount_due=49800), payment=payment()))

        assert event.amount_paise == 100

    def test_an_order_that_is_not_paid_says_nothing(self):
        assert deliver(envelope("order.paid", order=order(status="attempted"), payment=payment())) == []

    @pytest.mark.parametrize("kind", ["payment.captured", "payment.authorized"])
    def test_the_payment_events_beside_it_say_nothing_so_a_success_is_not_counted_twice(self, kind):
        assert deliver(envelope(kind, payment=payment())) == []

    def test_a_failed_payment_is_a_failure_for_its_order(self):
        failed = payment(
            status="failed", captured=False, error_code="BAD_REQUEST_ERROR", error_description="Payment failed"
        )

        (event,) = deliver(envelope("payment.failed", payment=failed), event_id="evt_failed")

        assert (event.event_id, event.kind, event.provider_ref, event.payment_ref) == (
            "evt_failed", "failed", "order_DESlLckIVRkHWj", "pay_DESlfW9H8K9uqM",
        )  # fmt: skip

    def test_a_failed_payment_with_no_order_says_nothing(self):
        assert deliver(envelope("payment.failed", payment=payment(order_id=None, status="failed"))) == []


class TestRefundsAndDisputes:
    @pytest.mark.parametrize("kind", ["refund.created", "refund.processed"])
    def test_a_processed_refund_is_that_refunds_own_amount_found_by_its_payment(self, kind):
        (event,) = deliver(envelope(kind, refund=refund(), payment=payment()), event_id="evt_x")

        assert event == PaymentEvent(
            event_id="refund:rfnd_FS8TWyPrCsa0OB", kind="refunded", provider_ref="", amount_paise=20000,
            currency="INR", occurred_at=datetime.fromtimestamp(CREATED, UTC), payment_ref="pay_DESlfW9H8K9uqM",
        )  # fmt: skip

    def test_created_and_processed_are_one_event_id_so_the_refund_counts_once(self):
        (created,) = deliver(envelope("refund.created", refund=refund(), payment=payment()), event_id="evt_a")
        (processed,) = deliver(envelope("refund.processed", refund=refund(), payment=payment()), event_id="evt_b")

        assert created.event_id == processed.event_id

    def test_two_refunds_of_one_payment_are_two_events(self):
        (first,) = deliver(envelope("refund.processed", refund=refund(id="rfnd_1", amount=10000)))
        (second,) = deliver(envelope("refund.processed", refund=refund(id="rfnd_2", amount=10000)))

        assert first.event_id != second.event_id

    @pytest.mark.parametrize("state", ["pending", "failed"])
    def test_a_refund_that_is_not_processed_says_nothing(self, state):
        for kind in ("refund.created", "refund.processed", "refund.failed"):
            assert deliver(envelope(kind, refund=refund(status=state), payment=payment())) == []

    def test_a_refund_needs_no_event_id_header_because_it_has_its_own(self):
        (event,) = deliver(envelope("refund.processed", refund=refund()), event_id=None)

        assert event.event_id == "refund:rfnd_FS8TWyPrCsa0OB"

    def test_a_dispute_raised_is_a_disputed_event_found_by_its_payment(self):
        dispute = {
            "id": "disp_EsIAlDcoUr8CaQ", "entity": "dispute", "payment_id": "pay_DESlfW9H8K9uqM", "amount": 39000,
            "currency": "INR", "amount_deducted": 0, "status": "open", "phase": "chargeback", "created_at": 1589907957,
        }  # fmt: skip

        (event,) = deliver(envelope("payment.dispute.created", payment=payment(), dispute=dispute), event_id="evt_d")

        assert (event.event_id, event.kind, event.provider_ref, event.payment_ref, event.amount_paise) == (
            "evt_d", "disputed", "", "pay_DESlfW9H8K9uqM", 39000,
        )  # fmt: skip

    @pytest.mark.parametrize("kind", ["won", "lost", "closed", "under_review", "action_required"])
    def test_the_other_dispute_events_say_nothing(self, kind):
        dispute = {"id": "disp_1", "payment_id": "pay_1", "amount": 100, "currency": "INR", "status": kind}

        assert deliver(envelope(f"payment.dispute.{kind}", payment=payment(), dispute=dispute)) == []


class TestTheEventIdHeader:
    @pytest.mark.parametrize("event_id", [None, "", "   "])
    def test_an_event_that_needs_it_and_has_none_is_refused(self, event_id):
        for event in (
            envelope("order.paid", order=order(), payment=payment()),
            envelope("payment.failed", payment=payment(status="failed")),
        ):
            with pytest.raises(InvalidWebhook):
                deliver(event, event_id=event_id)

    def test_an_event_that_says_nothing_needs_no_header(self):
        assert deliver(envelope("payment.captured", payment=payment()), event_id=None) == []


class TestWhatIsNotOurs:
    @pytest.mark.parametrize(
        "kind", ["payment.downtime.started", "refund.speed_changed", "ping", "subscription.charged"]
    )
    def test_an_event_nobody_here_cares_about_is_an_empty_list(self, kind):
        assert deliver(envelope(kind, payment=payment())) == []

    def test_an_event_of_ours_missing_what_it_needs_is_invalid(self):
        broken = envelope("order.paid", payment=payment())  # no order

        with pytest.raises(InvalidWebhook):
            deliver(broken)

    def test_a_body_that_is_not_json_is_invalid_even_when_signed(self):
        with pytest.raises(InvalidWebhook):
            deliver({}, body=b"not json at all")

    @pytest.mark.parametrize("body", [b"[]", b'"x"', b"{}", b'{"event":5}', b'{"event":"order.paid"}'])
    def test_a_json_body_that_is_not_an_event_is_invalid(self, body):
        with pytest.raises(InvalidWebhook):
            deliver({}, body=body)

    def test_the_reader_is_pure_so_a_test_can_use_it_alone(self):
        assert RazorpayEventReader().read(envelope("ping", payment=payment()), "evt_1") == []

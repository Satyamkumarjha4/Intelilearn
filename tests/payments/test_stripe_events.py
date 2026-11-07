"""Unit under test: `payments.stripe_events` (`StripeSignature`, `StripeEventReader`) and `StripeGateway.verify_webhook`
(credits plan §6.4, T23; phase 10.7), with events shaped as Stripe documents them (api/events/object,
api/checkout/sessions/object, api/refunds/object, api/disputes/object).

Why: a webhook is a stranger's HTTP request that moves money, so nothing in it counts until its signature is proved,
over the raw bytes and inside a five minute window. Once proved, Stripe's many event types have to become the four
things the rest of the app understands, exactly once each: a payment that cleared, one that did not, a refund and a
dispute. A refund is counted from the refund object (one event for one refund, whatever number of times Stripe says it),
because `charge.refunded` carries the running total and arrives in no promised order.

Use cases:
- the signature: a header computed over `t.body` with the endpoint secret is accepted, also with several `v1` values (a
  rolled secret) when any one matches, and with a `v0` beside it; a pinned vector computed outside the code is accepted
- refused as `InvalidWebhook`: a wrong secret, an altered body, a missing header, no `v1`, only a `v0`, a `t` that is
  not a number, a timestamp older than five minutes or more than five minutes ahead, an empty secret
- a timestamp just inside the window is accepted
- a completed session that is paid is a success (amount, currency in capitals, the payment intent, our session id); a
  completed session that is not paid yet says nothing; a delayed payment that succeeds is a success and one that fails
  is a failure; an expired session is a failure
- a refund (created, or updated while succeeded) is a refunded event for that refund's own amount, found by its payment
  intent; the same refund seen as created and updated has one event id; a refund that is pending, failed or cancelled
  says nothing
- `charge.refunded`, which carries the running total, says nothing, so a refund is never counted twice
- a dispute is a disputed event for its amount, found by its payment intent
- events nobody here cares about are an empty list, not an error; an event of ours that is missing what it needs, or a
  body that is not JSON, is an `InvalidWebhook`
- the event's time is Stripe's `created`
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from support.clock import FakeClock
from support.stripe import signature

from payments.config import GatewayConfig
from payments.errors import InvalidWebhook
from payments.gateway import PaymentEvent
from payments.stripe_events import StripeEventReader, StripeSignature
from payments.stripe_gateway import StripeGateway

SECRET = "whsec_" + "w" * 24  # not a real secret
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
CREATED = int((NOW - timedelta(seconds=5)).timestamp())


def sign(body: bytes, *, secret: str = SECRET, at: datetime = NOW, extra: str = "") -> str:
    return signature(body, secret, at, extra)


def gateway(secret: str = SECRET) -> StripeGateway:
    return StripeGateway(GatewayConfig({"secret_key": "sk_test_x", "webhook_secret": secret}), clock=FakeClock(NOW))


def deliver(event: dict, **sign_kwargs):
    body = json.dumps(event).encode()
    return gateway().verify_webhook({"Stripe-Signature": sign(body, **sign_kwargs)}, body)


def envelope(kind: str, obj: dict, event_id: str = "evt_1") -> dict:
    return {
        "id": event_id, "object": "event", "api_version": "2026-10-28.endive", "created": CREATED,
        "data": {"object": obj}, "livemode": False, "pending_webhooks": 1, "type": kind,
    }  # fmt: skip


def session(**fields) -> dict:
    return {
        "id": "cs_test_1", "object": "checkout.session", "amount_total": 49900, "currency": "inr",
        "payment_intent": "pi_3Abc", "payment_status": "paid", "status": "complete", **fields,
    }  # fmt: skip


def refund(**fields) -> dict:
    return {
        "id": "re_1", "object": "refund", "amount": 20000, "charge": "ch_1", "currency": "inr",
        "payment_intent": "pi_3Abc", "status": "succeeded", **fields,
    }  # fmt: skip


class TestTheSignature:
    BODY = b'{"id":"evt_test"}'

    def verify(self, header: str, body: bytes = BODY, secret: str = SECRET, now: datetime = NOW):
        StripeSignature(tolerance=timedelta(minutes=5)).verify(header, body, secret, now)

    def test_a_computed_signature_is_accepted(self):
        self.verify(sign(self.BODY))

    def test_a_vector_computed_outside_the_code_is_accepted(self):
        header = "t=1492774577,v1=22f7d74836ddad3284a2b80853dd2fe731655c1bfddcff3c3666a500cf3abd80"

        self.verify(header, secret="whsec_test_secret", now=datetime.fromtimestamp(1492774577 + 60, UTC))

    def test_any_one_of_several_v1_values_is_enough(self):
        stamp, digest = sign(self.BODY).split(",")  # the live secret's signature, among those of a rolled one

        self.verify(f"{stamp},v1={'0' * 64},{digest},v1={'f' * 64}")

    def test_a_v0_beside_it_is_ignored(self):
        self.verify(sign(self.BODY, extra=",v0=" + "a" * 64))

    @pytest.mark.parametrize("offset", [timedelta(minutes=4, seconds=59), -timedelta(minutes=4, seconds=59)])
    def test_a_timestamp_just_inside_the_window_is_accepted(self, offset):
        self.verify(sign(self.BODY, at=NOW + offset))

    def test_a_wrong_secret_is_refused(self):
        with pytest.raises(InvalidWebhook):
            self.verify(sign(self.BODY, secret="whsec_other"))

    def test_an_altered_body_is_refused(self):
        header = sign(self.BODY)

        with pytest.raises(InvalidWebhook):
            self.verify(header, body=b'{"id":"evt_test2"}')

    @pytest.mark.parametrize("offset", [timedelta(minutes=5, seconds=1), -timedelta(minutes=6)])
    def test_a_timestamp_outside_the_window_is_refused_even_when_it_is_signed_right(self, offset):
        with pytest.raises(InvalidWebhook):
            self.verify(sign(self.BODY, at=NOW - offset))

    @pytest.mark.parametrize(
        "header",
        ["", "garbage", "t=abc,v1=" + "a" * 64, "v1=" + "a" * 64, f"t={int(NOW.timestamp())}", "t=1,v0=" + "a" * 64],
    )
    def test_a_header_that_is_missing_or_unreadable_is_refused(self, header):
        with pytest.raises(InvalidWebhook):
            self.verify(header)

    def test_only_v0_is_not_enough(self):
        stamp = int(NOW.timestamp())
        digest = hmac.new(SECRET.encode(), f"{stamp}.".encode() + self.BODY, hashlib.sha256).hexdigest()

        with pytest.raises(InvalidWebhook):
            self.verify(f"t={stamp},v0={digest}")

    def test_an_empty_secret_refuses_everything(self):
        with pytest.raises(InvalidWebhook):
            self.verify(sign(self.BODY, secret=""), secret="")

    def test_a_missing_header_is_refused_by_the_gateway(self):
        with pytest.raises(InvalidWebhook):
            gateway().verify_webhook({}, self.BODY)

    def test_the_gateway_finds_the_header_whatever_its_case(self):
        body = json.dumps(envelope("customer.created", {"id": "cus_1"})).encode()

        assert gateway().verify_webhook({"stripe-signature": sign(body)}, body) == []


class TestPaymentsThatClearOrFail:
    def test_a_paid_completed_session_is_a_success(self):
        (event,) = deliver(envelope("checkout.session.completed", session()))

        assert event == PaymentEvent(
            event_id="evt_1", kind="succeeded", provider_ref="cs_test_1", amount_paise=49900, currency="INR",
            occurred_at=datetime.fromtimestamp(CREATED, UTC), payment_ref="pi_3Abc",
        )  # fmt: skip

    def test_a_completed_session_not_yet_paid_says_nothing(self):
        assert deliver(envelope("checkout.session.completed", session(payment_status="unpaid"))) == []

    def test_a_delayed_payment_that_succeeds_is_a_success(self):
        (event,) = deliver(envelope("checkout.session.async_payment_succeeded", session()))

        assert (event.kind, event.provider_ref, event.amount_paise) == ("succeeded", "cs_test_1", 49900)

    def test_a_delayed_payment_that_fails_is_a_failure(self):
        (event,) = deliver(envelope("checkout.session.async_payment_failed", session(payment_status="unpaid")))

        assert (event.kind, event.provider_ref) == ("failed", "cs_test_1")

    def test_an_expired_session_is_a_failure(self):
        (event,) = deliver(
            envelope(
                "checkout.session.expired", session(status="expired", payment_status="unpaid", payment_intent=None)
            )
        )

        assert (event.kind, event.provider_ref, event.payment_ref) == ("failed", "cs_test_1", "")


class TestRefundsAndDisputes:
    @pytest.mark.parametrize("kind", ["refund.created", "refund.updated"])
    def test_a_refund_is_that_refunds_own_amount_found_by_its_payment_intent(self, kind):
        (event,) = deliver(envelope(kind, refund()))

        assert event == PaymentEvent(
            event_id="refund:re_1", kind="refunded", provider_ref="", amount_paise=20000, currency="INR",
            occurred_at=datetime.fromtimestamp(CREATED, UTC), payment_ref="pi_3Abc",
        )  # fmt: skip

    def test_a_refund_seen_as_created_and_as_updated_is_one_event_id(self):
        (created,) = deliver(envelope("refund.created", refund(), "evt_a"))
        (updated,) = deliver(envelope("refund.updated", refund(), "evt_b"))

        assert created.event_id == updated.event_id

    def test_two_refunds_of_one_payment_are_two_events(self):
        (first,) = deliver(envelope("refund.created", refund(id="re_1", amount=10000)))
        (second,) = deliver(envelope("refund.created", refund(id="re_2", amount=10000)))

        assert first.event_id != second.event_id

    @pytest.mark.parametrize("state", ["pending", "requires_action", "failed", "canceled"])
    def test_a_refund_that_has_not_succeeded_says_nothing(self, state):
        assert deliver(envelope("refund.created", refund(status=state))) == []

    def test_charge_refunded_says_nothing_because_it_carries_the_running_total(self):
        charge = {
            "id": "ch_1",
            "object": "charge",
            "payment_intent": "pi_3Abc",
            "amount": 49900,
            "amount_refunded": 20000,
        }

        assert deliver(envelope("charge.refunded", charge)) == []

    def test_a_dispute_is_a_disputed_event_found_by_its_payment_intent(self):
        dispute = {
            "id": "du_1", "object": "dispute", "charge": "ch_1", "payment_intent": "pi_3Abc", "amount": 49900,
            "currency": "inr", "status": "needs_response",
        }  # fmt: skip

        (event,) = deliver(envelope("charge.dispute.created", dispute, "evt_d"))

        assert (event.event_id, event.kind, event.provider_ref, event.payment_ref, event.amount_paise) == (
            "evt_d", "disputed", "", "pi_3Abc", 49900,
        )  # fmt: skip
        assert event.currency == "INR"


class TestWhatIsNotOurs:
    @pytest.mark.parametrize("kind", ["customer.created", "payment_intent.succeeded", "charge.succeeded", "ping"])
    def test_an_event_nobody_here_cares_about_is_an_empty_list(self, kind):
        assert deliver(envelope(kind, {"id": "x_1", "object": "thing"})) == []

    def test_an_event_of_ours_missing_what_it_needs_is_invalid(self):
        broken = envelope("checkout.session.completed", {"payment_status": "paid"})

        with pytest.raises(InvalidWebhook):
            deliver(broken)

    def test_a_body_that_is_not_json_is_invalid_even_when_signed(self):
        body = b"not json at all"

        with pytest.raises(InvalidWebhook):
            gateway().verify_webhook({"Stripe-Signature": sign(body)}, body)

    @pytest.mark.parametrize("body", [b"[]", b'"x"', b"{}", b'{"id":"e","type":"refund.created"}'])
    def test_a_json_body_that_is_not_an_event_is_invalid(self, body):
        with pytest.raises(InvalidWebhook):
            gateway().verify_webhook({"Stripe-Signature": sign(body)}, body)

    def test_the_reader_is_pure_so_a_test_can_use_it_alone(self):
        assert StripeEventReader().read(envelope("customer.created", {"id": "c"})) == []

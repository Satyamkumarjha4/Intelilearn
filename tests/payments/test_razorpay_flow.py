"""Unit under test: the buying path with `RazorpayGateway` in the real seats of the app (credits plan §5.8, §13.3; phase
10.8): the orders endpoint, the signed webhook view, the reconciler and the admin's Refund action, with only Razorpay's
HTTPS replaced by `httpx.MockTransport`.

Why: the adapter's own tests prove what it sends and reads; these prove it is plugged in right, and that adding it
needed no change anywhere else. An order made for Razorpay hands the browser a client checkout and keeps Razorpay's
order id; a callback signed with Razorpay's scheme, and only that, grants credits; a replayed callback (Razorpay signs
no timestamp) is stopped by its event id; a refund started in the admin carries the form's token to Razorpay and is
taken back from the credits when its event arrives, by the payment; and the return page's lookup settles an order when
no webhook came.

Use cases:
- an order for Razorpay goes to Razorpay with our order id and answers with a client checkout for the `razorpay`
  adapter; the order keeps Razorpay's order id and the browser is told no secret
- a validly signed `order.paid` grants the credits and records the payment id; the same event id again (a replay, or a
  retry) grants nothing more; a callback signed with another secret is a `400`; one with no event id header is a `400`
- `payment.failed` is recorded as a failed attempt and the order stays open; a success after it grants once, and with
  no success the order ends only at its own deadline and grants nothing; an amount that is not
  the order's grants nothing
- asking Razorpay (the return page's path) settles a paid order with no webhook, and leaves an open one waiting
- the admin's Refund asks Razorpay for what is left against the payment, with the token as `X-Refund-Idempotency` once
  however often the form is sent; the credits come back only when `refund.processed` arrives; `refund.created` for the
  same refund changes nothing more
- two partial refunds add up to the whole; a dispute takes the credits back by the payment
- with Stripe and Razorpay both on, the buy page is told of both, and an order can be made for either
"""

import json
import uuid
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from support.razorpay import envelope, sign
from support.razorpay import order as rzp_order
from support.razorpay import payment as rzp_payment
from support.razorpay import refund as rzp_refund
from support.stripe import Wire

from credits.ledger import Ledger
from payments.config import GatewayConfig
from payments.models import PaymentEventLog, PaymentOrder
from payments.razorpay_gateway import RazorpayGateway
from payments.reconcile import OrderReconciler
from payments.registry import PaymentGateways
from payments.stripe_gateway import StripeGateway

pytestmark = pytest.mark.django_db

HOOK = "/api/payments/webhooks/razorpay"
KEY_ID, KEY_SECRET, SECRET = "rzp_test_" + "i" * 14, "s" * 24, "h" * 20  # not real keys
RZP_ID, PAY_ID = "order_RB58MiP5SPFYyM", "pay_N8FUmetkCE2hZP"
CREATED_ORDER = {
    "id": RZP_ID, "entity": "order", "amount": 10000, "amount_paid": 0, "amount_due": 10000, "currency": "INR",
    "receipt": "r", "status": "created", "attempts": 0, "notes": {}, "created_at": 1756455561,
}  # fmt: skip


@pytest.fixture
def razorpay(db, user, settings, monkeypatch):
    """Razorpay the only way to pay, its HTTPS replaced by a `Wire` the test can read and script."""
    from credits.plans.seed import PlanSeed

    wire = Wire((200, CREATED_ORDER))

    class WiredRazorpay(RazorpayGateway):
        @classmethod
        def from_settings(cls):
            return cls(GatewayConfig.from_settings(cls.config_names()), client=wire.client())

    monkeypatch.setitem(PaymentGateways.REGISTERED, "razorpay", WiredRazorpay)
    settings.PAYMENT_GATEWAYS_ENABLED, settings.PAYMENT_DEFAULT_GATEWAY = ["razorpay"], "razorpay"
    settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET, settings.RAZORPAY_WEBHOOK_SECRET = (
        KEY_ID,
        KEY_SECRET,
        SECRET,
    )
    settings.PAYMENT_RETURN_BASE_URL = "http://shop.test"
    PlanSeed().apply()
    return wire


def buy(client, credits=100, **extra):
    response = client.post("/api/payments/orders", {"plan": "one_time", "credits": credits, **extra}, format="json")
    assert response.status_code == 201, response.content
    return response


def rzp_order_paid(**fields) -> dict:
    return rzp_order(**{"id": RZP_ID, "amount": 10000, "amount_paid": 10000, **fields})


def paid_event(event_id="evt_paid", **order_fields) -> tuple[dict, str]:
    return envelope(
        "order.paid", order=rzp_order_paid(**order_fields), payment=rzp_payment(id=PAY_ID, order_id=RZP_ID)
    ), event_id


def failed_attempt() -> dict:
    return envelope("payment.failed", payment=rzp_payment(id=PAY_ID, order_id=RZP_ID, status="failed", captured=False))


def deliver(body: dict, event_id: str | None = "evt_1", *, secret: str = SECRET, client: Client | None = None):
    raw = json.dumps(body).encode()
    extra = {"HTTP_X_RAZORPAY_EVENT_ID": event_id} if event_id is not None else {}
    return (client or Client(enforce_csrf_checks=True)).generic(
        "POST", HOOK, raw, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sign(raw, secret), **extra
    )


def pay(body_and_id) -> object:
    body, event_id = body_and_id
    return deliver(body, event_id)


@pytest.fixture
def order(razorpay, signed_in_client):
    return PaymentOrder.objects.get(pk=buy(signed_in_client).json()["id"])


@pytest.fixture
def paid(order):
    assert pay(paid_event()).status_code == 200
    order.refresh_from_db()
    return order


@pytest.fixture
def staff(client, db):
    from accounts.models import User

    boss = User.objects.create_user("boss@example.com", password="x-staff-pass-1", name="Boss")
    boss.is_staff = boss.is_superuser = True
    boss.save()
    client.force_login(boss)
    return boss


def ask_refund(client, order, token=None, amount=None):
    body = {"action": "refund", "_selected_action": [str(order.pk)]}
    if token:
        body["refund_token"] = token
    if amount:
        body["refund_amount"] = amount
    return client.post(reverse("admin:payments_paymentorder_changelist"), body, follow=True)


class TestBuying:
    def test_the_order_goes_to_razorpay_with_our_id_and_the_browser_gets_a_client_checkout(
        self, razorpay, signed_in_client
    ):
        response = buy(signed_in_client)

        body = response.json()
        assert body["checkout"]["kind"] == "client" and body["checkout"]["adapter"] == "razorpay"
        assert body["checkout"]["client"] | {"key": KEY_ID} == body["checkout"]["client"]
        assert body["checkout"]["client"]["order_id"] == RZP_ID and body["checkout"]["client"]["amount"] == 10000
        assert KEY_SECRET not in response.content.decode() and SECRET not in response.content.decode()
        sent = json.loads(razorpay.sent.content)
        assert sent["receipt"] == body["id"] and sent["notes"] == {"order_id": body["id"]} and sent["amount"] == 10000
        stored = PaymentOrder.objects.get(pk=body["id"])
        assert (stored.gateway, stored.status, stored.provider_ref) == ("razorpay", "pending", RZP_ID)

    def test_razorpay_is_the_gateway_the_buy_page_is_told_about(self, razorpay, signed_in_client):
        body = signed_in_client.get("/api/payments/gateways").json()

        assert body == {"gateways": [{"key": "razorpay", "display_name": "Razorpay"}], "default": "razorpay"}

    def test_with_stripe_and_razorpay_both_on_the_page_is_told_of_both_and_either_can_be_chosen(
        self, razorpay, signed_in_client, settings, monkeypatch
    ):
        stripe_wire = Wire((200, {"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}))

        class WiredStripe(StripeGateway):
            @classmethod
            def from_settings(cls):
                return cls(GatewayConfig.from_settings(cls.config_names()), client=stripe_wire.client())

        monkeypatch.setitem(PaymentGateways.REGISTERED, "stripe", WiredStripe)
        settings.PAYMENT_GATEWAYS_ENABLED = ["stripe", "razorpay"]
        settings.STRIPE_SECRET_KEY, settings.STRIPE_WEBHOOK_SECRET = "sk_test_" + "k" * 24, "whsec_" + "w" * 24

        listed = signed_in_client.get("/api/payments/gateways").json()
        stripe_order = buy(signed_in_client, gateway="stripe").json()
        razorpay_order = buy(signed_in_client, gateway="razorpay").json()

        assert [g["key"] for g in listed["gateways"]] == ["stripe", "razorpay"]
        assert stripe_order["checkout"]["kind"] == "redirect" and razorpay_order["checkout"]["kind"] == "client"


class TestTheSignedCallback:
    def test_order_paid_grants_once_and_records_the_payment(self, order, user):
        first = pay(paid_event("evt_paid"))

        order.refresh_from_db()
        assert first.status_code == 200
        assert (order.status, order.payment_ref) == ("fulfilled", PAY_ID) and Ledger().balance(user) == 100

    def test_the_same_event_id_again_is_stopped_by_the_event_id_and_grants_nothing_more(self, order, user):
        pay(paid_event("evt_paid"))

        replay = pay(paid_event("evt_paid"))

        assert replay.status_code == 200 and Ledger().balance(user) == 100
        assert PaymentEventLog.objects.filter(event_id="evt_paid").count() == 1
        assert PaymentEventLog.objects.get(event_id="evt_paid").outcome == "applied"

    def test_the_same_payment_under_another_event_id_grants_once(self, order, user):
        pay(paid_event("evt_1"))
        pay(paid_event("evt_2"))

        assert Ledger().balance(user) == 100

    def test_another_secret_grants_nothing(self, order, user):
        body, event_id = paid_event()

        response = deliver(body, event_id, secret="not-the-webhook-secret")

        order.refresh_from_db()
        assert response.status_code == 400 and order.status == "pending" and Ledger().balance(user) == 0
        assert not PaymentEventLog.objects.exists()

    def test_the_api_key_secret_is_not_accepted_in_place_of_the_webhook_secret(self, order, user):
        body, event_id = paid_event()

        assert deliver(body, event_id, secret=KEY_SECRET).status_code == 400

    def test_a_signed_success_with_no_event_id_header_is_refused(self, order, user):
        body, _ = paid_event()

        response = deliver(body, None)

        assert response.status_code == 400 and Ledger().balance(user) == 0

    def test_a_failed_attempt_is_recorded_and_the_order_stays_open_for_the_next_one(self, order, user):
        pay((failed_attempt(), "evt_failed"))

        order.refresh_from_db()
        assert (order.status, order.failure_reason) == ("pending", "") and Ledger().balance(user) == 0
        logged = PaymentEventLog.objects.get(event_id="evt_failed")
        assert (logged.kind, logged.outcome, logged.order_id) == ("attempt_failed", "applied", order.pk)

    def test_a_failed_attempt_then_a_success_in_the_same_order_grants_once(self, order, user):
        pay((failed_attempt(), "evt_failed_1"))
        pay((failed_attempt(), "evt_failed_2"))

        pay(paid_event("evt_paid"))
        pay(paid_event("evt_paid_again"))

        order.refresh_from_db()
        assert order.status == "fulfilled" and Ledger().balance(user) == 100
        assert PaymentEventLog.objects.filter(kind="attempt_failed").count() == 2

    def test_failed_attempts_only_then_the_deadline_grants_nothing(self, order, razorpay, user):
        pay((failed_attempt(), "evt_failed"))
        PaymentOrder.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(hours=26), expires_at=timezone.now() - timedelta(hours=1)
        )
        razorpay.answers = [(200, {**CREATED_ORDER, "status": "attempted", "attempts": 1})]

        report = OrderReconciler().run()

        order.refresh_from_db()
        assert (order.status, report.expired) == ("expired", 1) and Ledger().balance(user) == 0
        assert order.purchase.status == "void"

    def test_a_success_after_the_deadline_still_grants_because_the_money_was_taken(self, order, user):
        pay((failed_attempt(), "evt_failed"))
        PaymentOrder.objects.filter(pk=order.pk).update(status="expired")

        pay(paid_event("evt_late"))

        order.refresh_from_db()
        assert order.status == "fulfilled" and Ledger().balance(user) == 100

    def test_an_amount_that_is_not_the_orders_grants_nothing(self, order, user):
        pay(paid_event("evt_short", amount_paid=100, amount_due=9900))

        order.refresh_from_db()
        assert order.status == "pending" and Ledger().balance(user) == 0
        assert PaymentEventLog.objects.get().outcome == "amount_mismatch"

    def test_the_payment_events_beside_order_paid_change_nothing(self, order, user):
        captured = envelope("payment.captured", payment=rzp_payment(id=PAY_ID, order_id=RZP_ID))

        response = pay((captured, "evt_cap"))

        assert response.status_code == 200 and Ledger().balance(user) == 0 and not PaymentEventLog.objects.exists()


class TestAskingRazorpayInsteadOfWaiting:
    def test_a_paid_order_settles_with_no_webhook(self, order, razorpay, user):
        paid_order = {**CREATED_ORDER, "status": "paid", "amount_paid": 10000, "amount_due": 0}
        razorpay.answers = [
            (200, paid_order),
            (200, {"entity": "collection", "count": 1, "items": [rzp_payment(id=PAY_ID, order_id=RZP_ID)]}),
        ]

        OrderReconciler().refresh(order)

        order.refresh_from_db()
        assert order.status == "fulfilled" and order.payment_ref == PAY_ID and Ledger().balance(user) == 100

    def test_an_attempted_order_leaves_it_waiting(self, order, razorpay, user):
        razorpay.answers = [(200, {**CREATED_ORDER, "status": "attempted", "attempts": 1})]

        OrderReconciler().refresh(order)

        order.refresh_from_db()
        assert order.status == "pending" and Ledger().balance(user) == 0

    def test_the_callback_after_that_changes_nothing_more(self, order, razorpay, user):
        razorpay.answers = [
            (200, {**CREATED_ORDER, "status": "paid", "amount_paid": 10000}),
            (200, {"entity": "collection", "count": 1, "items": [rzp_payment(id=PAY_ID, order_id=RZP_ID)]}),
        ]
        OrderReconciler().refresh(order)

        pay(paid_event("evt_paid"))

        assert Ledger().balance(user) == 100


class TestRefundsAndDisputes:
    def test_the_admin_refunds_with_the_forms_token_once_and_the_credits_return_with_the_event(
        self, client, staff, paid, razorpay, user
    ):
        razorpay.answers = [(200, {"id": "rfnd_1", "amount": 10000, "status": "processed", "payment_id": PAY_ID})]
        token = str(uuid.uuid4())

        ask_refund(client, paid, token)
        ask_refund(client, paid, token)

        assert len([r for r in razorpay.requests if r.url.path.endswith("/refund")]) == 1
        assert razorpay.sent.url.path == f"/v1/payments/{PAY_ID}/refund" and json.loads(razorpay.sent.content) == {
            "amount": 10000
        }
        assert razorpay.sent.headers["x-refund-idempotency"] == f"refund-{token}-{paid.pk}"
        assert Ledger().balance(user) == 100  # not yet: Razorpay has not said so

        pay(
            (
                envelope(
                    "refund.processed",
                    refund=rzp_refund(id="rfnd_1", amount=10000, payment_id=PAY_ID),
                    payment=rzp_payment(id=PAY_ID),
                ),
                "evt_r",
            )
        )

        paid.refresh_from_db()
        assert Ledger().balance(user) == 0 and paid.refunded_paise == 10000 and paid.status == "fulfilled"

    def test_the_same_refund_seen_as_created_and_processed_counts_once(self, paid, user):
        def body(kind):
            refund = rzp_refund(id="rfnd_1", amount=4000, payment_id=PAY_ID)
            return envelope(kind, refund=refund, payment=rzp_payment(id=PAY_ID))

        pay((body("refund.created"), "evt_a"))
        pay((body("refund.processed"), "evt_b"))

        paid.refresh_from_db()
        assert paid.refunded_paise == 4000 and Ledger().balance(user) == 60

    def test_two_partial_refunds_add_up_to_the_whole(self, paid, user):
        for number, amount in (("1", 4000), ("2", 6000)):
            refund = rzp_refund(id=f"rfnd_{number}", amount=amount, payment_id=PAY_ID)
            pay((envelope("refund.processed", refund=refund, payment=rzp_payment(id=PAY_ID)), f"evt_r{number}"))

        paid.refresh_from_db()
        assert paid.refunded_paise == 10000 and Ledger().balance(user) == 0

    def test_a_refund_still_pending_takes_nothing_until_it_is_processed(self, paid, user):
        pending = rzp_refund(id="rfnd_1", amount=10000, payment_id=PAY_ID, status="pending")
        pay((envelope("refund.created", refund=pending, payment=rzp_payment(id=PAY_ID)), "evt_a"))
        assert Ledger().balance(user) == 100

        done = rzp_refund(id="rfnd_1", amount=10000, payment_id=PAY_ID)
        pay((envelope("refund.processed", refund=done, payment=rzp_payment(id=PAY_ID)), "evt_b"))

        assert Ledger().balance(user) == 0

    def test_a_dispute_takes_the_credits_back_by_the_payment(self, paid, user):
        dispute = {"id": "disp_1", "entity": "dispute", "payment_id": PAY_ID, "amount": 10000, "currency": "INR",
                   "status": "open", "phase": "chargeback"}  # fmt: skip

        pay((envelope("payment.dispute.created", payment=rzp_payment(id=PAY_ID), dispute=dispute), "evt_d"))

        assert Ledger().balance(user) == 0

"""Unit under test: the buying path with `StripeGateway` in the real seats of the app (credits plan §5.8, §13.3; phase
10.7): the orders endpoint, the signed webhook view, the reconciler and the admin's Refund action, with only Stripe's
HTTPS replaced by `httpx.MockTransport`.

Why: the adapter's own tests prove what it sends and reads; these prove it is plugged in right. That an order made for
Stripe carries our id and keeps Stripe's session id, that a callback signed with Stripe's scheme, and only that, grants
credits (once), that a refund started in the admin is taken back from the credits when Stripe's refund event arrives (by
the payment, not the session) and a second partial one adds up, and that the return page's lookup settles an order when
no webhook ever came.

Use cases:
- an order for Stripe goes to Stripe with our order id and answers with a redirect to Stripe's page; the order keeps the
  session id
- a validly signed `checkout.session.completed` grants the credits and records the payment intent; the same callback
  again, a callback signed with another secret, and one signed too long ago grant nothing more (the last two are `400`)
- an unpaid completion waits for the delayed payment's own event; an expired session ends the order; a session whose
  amount is not the order's grants nothing
- asking Stripe (the return page's path) settles a paid order with no webhook, and leaves an open one waiting
- the admin's Refund asks Stripe for what is left, against the payment intent; the credits come back only when the
  `refund.created` event arrives; `refund.updated` for the same refund and `charge.refunded` change nothing more
- two partial refunds add up to the whole; a dispute takes the credits back by the payment intent
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from support.stripe import Wire, signature

from credits.ledger import Ledger
from payments.config import GatewayConfig
from payments.models import PaymentEventLog, PaymentOrder
from payments.reconcile import OrderReconciler
from payments.registry import PaymentGateways
from payments.stripe_gateway import StripeGateway

pytestmark = pytest.mark.django_db

SECRET = "whsec_" + "w" * 24  # not a real secret
HOOK = "/api/payments/webhooks/stripe"
SESSION_ID, INTENT = "cs_test_flow1", "pi_3Flow1"
SESSION = {
    "id": SESSION_ID, "object": "checkout.session", "amount_total": 10000, "currency": "inr", "mode": "payment",
    "payment_intent": None, "payment_status": "unpaid", "status": "open",
    "url": f"https://checkout.stripe.com/c/pay/{SESSION_ID}#frag",
}  # fmt: skip


@pytest.fixture
def stripe(db, user, settings, monkeypatch):
    """Stripe the only way to pay, its HTTPS replaced by a `Wire` the test can read and script."""
    from credits.plans.seed import PlanSeed

    wire = Wire((200, SESSION))

    class WiredStripe(StripeGateway):
        @classmethod
        def from_settings(cls):
            return cls(GatewayConfig.from_settings(cls.config_names()), client=wire.client())

    monkeypatch.setitem(PaymentGateways.REGISTERED, "stripe", WiredStripe)
    settings.PAYMENT_GATEWAYS_ENABLED, settings.PAYMENT_DEFAULT_GATEWAY = ["stripe"], "stripe"
    settings.STRIPE_SECRET_KEY, settings.STRIPE_WEBHOOK_SECRET = "sk_test_" + "k" * 24, SECRET
    settings.PAYMENT_RETURN_BASE_URL = "http://shop.test"
    PlanSeed().apply()
    return wire


def buy(client, credits=100):
    response = client.post("/api/payments/orders", {"plan": "one_time", "credits": credits}, format="json")
    assert response.status_code == 201, response.content
    return response


def event(kind: str, obj: dict, event_id: str | None = None) -> dict:
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex[:12]}", "object": "event", "api_version": "2026-10-28.endive",
        "created": int(datetime.now(UTC).timestamp()), "data": {"object": obj}, "livemode": False, "type": kind,
    }  # fmt: skip


def paid_session(**fields) -> dict:
    return {**SESSION, "status": "complete", "payment_status": "paid", "payment_intent": INTENT, **fields}


def refund_object(amount: int, refund_id: str = "re_1", **fields) -> dict:
    return {
        "id": refund_id, "object": "refund", "amount": amount, "currency": "inr", "payment_intent": INTENT,
        "status": "succeeded", **fields,
    }  # fmt: skip


def deliver(body: dict, *, secret: str = SECRET, at: datetime | None = None, client: Client | None = None):
    raw = json.dumps(body).encode()
    return (client or Client(enforce_csrf_checks=True)).generic(
        "POST", HOOK, raw, content_type="application/json",
        HTTP_STRIPE_SIGNATURE=signature(raw, secret, at or datetime.now(UTC)),
    )  # fmt: skip


@pytest.fixture
def order(stripe, signed_in_client):
    return PaymentOrder.objects.get(pk=buy(signed_in_client).json()["id"])


@pytest.fixture
def paid(order):
    assert deliver(event("checkout.session.completed", paid_session())).status_code == 200
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


def ask_refund(client, order):
    return client.post(
        reverse("admin:payments_paymentorder_changelist"),
        {"action": "refund", "_selected_action": [str(order.pk)]},
        follow=True,
    )


class TestBuying:
    def test_the_order_goes_to_stripe_with_our_id_and_the_learner_to_stripes_page(self, stripe, signed_in_client):
        response = buy(signed_in_client)

        body = response.json()
        assert body["checkout"] == {"kind": "redirect", "redirect_url": SESSION["url"]}
        assert stripe.form()["client_reference_id"] == body["id"]
        assert stripe.form()["line_items[0][price_data][unit_amount]"] == "10000"
        order = PaymentOrder.objects.get(pk=body["id"])
        assert (order.gateway, order.status, order.provider_ref) == ("stripe", "pending", SESSION_ID)

    def test_stripe_is_the_gateway_the_buy_page_is_told_about(self, stripe, signed_in_client):
        body = signed_in_client.get("/api/payments/gateways").json()

        assert body == {"gateways": [{"key": "stripe", "display_name": "Stripe"}], "default": "stripe"}


class TestTheSignedCallback:
    def test_a_paid_completion_grants_once_and_records_the_payment_intent(self, order, user):
        body = event("checkout.session.completed", paid_session(), "evt_paid")

        first, again = deliver(body), deliver(body)

        order.refresh_from_db()
        assert (first.status_code, again.status_code) == (200, 200)
        assert (order.status, order.payment_ref) == ("fulfilled", INTENT) and Ledger().balance(user) == 100
        assert PaymentEventLog.objects.filter(event_id="evt_paid").count() == 1

    def test_another_secret_or_an_old_signature_grants_nothing(self, order, user):
        body = event("checkout.session.completed", paid_session())

        wrong = deliver(body, secret="whsec_someone_else")
        old = deliver(body, at=datetime.now(UTC) - timedelta(minutes=6))

        order.refresh_from_db()
        assert (wrong.status_code, old.status_code) == (400, 400)
        assert order.status == "pending" and Ledger().balance(user) == 0 and not PaymentEventLog.objects.exists()

    def test_an_unpaid_completion_waits_for_the_delayed_payment_which_then_grants(self, order, user):
        deliver(event("checkout.session.completed", paid_session(payment_status="unpaid")))
        order.refresh_from_db()
        assert order.status == "pending" and Ledger().balance(user) == 0

        deliver(event("checkout.session.async_payment_succeeded", paid_session()))

        order.refresh_from_db()
        assert order.status == "fulfilled" and Ledger().balance(user) == 100

    def test_an_expired_session_ends_the_order(self, order, user):
        deliver(event("checkout.session.expired", {**SESSION, "status": "expired", "url": None}))

        order.refresh_from_db()
        assert order.status == "failed" and Ledger().balance(user) == 0

    def test_a_session_for_another_amount_grants_nothing(self, order, user):
        deliver(event("checkout.session.completed", paid_session(amount_total=100)))

        order.refresh_from_db()
        assert order.status == "pending" and Ledger().balance(user) == 0
        assert PaymentEventLog.objects.get().outcome == "amount_mismatch"

    def test_an_event_we_do_not_act_on_is_answered_and_ignored(self, order):
        response = deliver(event("customer.created", {"id": "cus_1", "object": "customer"}))

        assert response.status_code == 200 and not PaymentEventLog.objects.exists()


class TestAskingStripeInsteadOfWaiting:
    def test_a_paid_session_settles_an_order_with_no_webhook(self, order, stripe, user):
        stripe.answers = [(200, paid_session())]

        OrderReconciler().refresh(order)

        order.refresh_from_db()
        assert order.status == "fulfilled" and order.payment_ref == INTENT and Ledger().balance(user) == 100
        assert (stripe.sent.method, stripe.sent.url.path) == ("GET", f"/v1/checkout/sessions/{SESSION_ID}")

    def test_an_open_session_leaves_it_waiting(self, order, stripe, user):
        OrderReconciler().refresh(order)

        order.refresh_from_db()
        assert order.status == "pending" and Ledger().balance(user) == 0

    def test_the_callback_after_that_changes_nothing_more(self, order, stripe, user):
        stripe.answers = [(200, paid_session())]
        OrderReconciler().refresh(order)

        deliver(event("checkout.session.completed", paid_session()))

        assert Ledger().balance(user) == 100


class TestRefundsAndDisputes:
    def test_the_admin_refunds_through_stripe_and_the_credits_return_with_its_event(
        self, client, staff, paid, stripe, user
    ):
        stripe.answers = [(200, refund_object(10000))]

        ask_refund(client, paid)

        assert (stripe.sent.method, stripe.sent.url.path) == ("POST", "/v1/refunds")
        assert stripe.form() == {"payment_intent": INTENT, "amount": "10000"}
        assert Ledger().balance(user) == 100  # not yet: Stripe has not said so

        deliver(event("refund.created", refund_object(10000)))

        paid.refresh_from_db()
        assert Ledger().balance(user) == 0 and paid.refunded_paise == 10000 and paid.status == "fulfilled"

    def test_the_same_refund_seen_again_and_the_charges_total_change_nothing_more(self, paid, user):
        deliver(event("refund.created", refund_object(4000)))

        deliver(event("refund.updated", refund_object(4000)))
        deliver(event("charge.refunded", {"id": "ch_1", "payment_intent": INTENT, "amount_refunded": 4000}))

        paid.refresh_from_db()
        assert paid.refunded_paise == 4000 and Ledger().balance(user) == 60

    def test_two_partial_refunds_add_up_to_the_whole(self, paid, user):
        deliver(event("refund.created", refund_object(4000, "re_1")))
        deliver(event("refund.created", refund_object(6000, "re_2")))

        paid.refresh_from_db()
        assert paid.refunded_paise == 10000 and Ledger().balance(user) == 0

    def test_a_refund_still_pending_takes_nothing_until_it_succeeds(self, paid, user):
        deliver(event("refund.created", refund_object(10000, status="pending")))
        assert Ledger().balance(user) == 100

        deliver(event("refund.updated", refund_object(10000)))

        assert Ledger().balance(user) == 0

    def test_a_dispute_takes_the_credits_back_by_the_payment_intent(self, paid, user):
        dispute = {"id": "du_1", "object": "dispute", "payment_intent": INTENT, "amount": 10000, "currency": "inr"}

        deliver(event("charge.dispute.created", dispute))

        assert Ledger().balance(user) == 0

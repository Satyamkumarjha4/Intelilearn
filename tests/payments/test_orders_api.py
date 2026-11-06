"""Unit under test: `GET /api/payments/gateways`, `POST` and `GET /api/payments/orders` and
`GET /api/payments/orders/{id}` (credits plan §8.2, §8.5, T24).

Why: this is what the buy page is built on. It must never take a price from the client, must refuse a provider that is
off, must say plainly when the provider is down, must be private to the learner, and above all the page a learner comes
back to after paying must never grant anything itself: credits come from a signed callback or from the server asking the
provider.

Use cases:
- all of them need a signed-in learner; the gateways list is the enabled ones and the default (empty with none on)
- an order is made from a plan and a quantity or credits and carries the server's amount and the checkout; a price sent
  by the client is not read; an unknown plan, a bad amount, a gateway that is off, a full queue, a fourth waiting
  payment and a provider outage are each refused with their own code and nothing is made (an outage leaves a failed
  order)
- the same `Idempotency-Key` makes one order; starting a payment is rate limited
- the list holds only the learner's own orders, newest first
- an order is private: another learner's is a `404`
- the order page grants nothing on its own: a waiting order under 30 seconds old is not even asked about; an older one
  makes the server ask the provider, and only a paid answer grants; an unreachable provider changes nothing
- the order shows what it was for in words a screen can use, and never a secret
- another cookie-authenticated unsafe request keeps its CSRF check
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.throttling import SimpleRateThrottle

from credits.ledger import Ledger
from payments.errors import GatewayUnavailable
from payments.models import PaymentOrder

pytestmark = pytest.mark.django_db

ORDERS, GATEWAYS = "/api/payments/orders", "/api/payments/gateways"


def make(client, **body):
    return client.post(ORDERS, {"plan": "one_time", "credits": 100, **body}, format="json")


class TestAccess:
    @pytest.mark.parametrize("url", [GATEWAYS, ORDERS, f"{ORDERS}/{uuid.uuid4()}"])
    def test_they_need_a_signed_in_learner(self, api_client, url):
        assert api_client.get(url).status_code == 401

    def test_starting_a_payment_needs_one_too(self, api_client):
        assert api_client.post(ORDERS, {"plan": "one_time", "credits": 100}, format="json").status_code == 401

    def test_a_cookie_authenticated_post_keeps_its_csrf_check(self, payments, signed_in_client):
        signed_in_client.handler.enforce_csrf_checks = True  # the way a browser's request is treated

        response = make(signed_in_client)

        assert response.status_code == 403 and not PaymentOrder.objects.exists()


class TestTheGateways:
    def test_they_are_the_enabled_ones_and_the_default(self, payments, signed_in_client):
        assert signed_in_client.get(GATEWAYS).json() == {
            "gateways": [{"key": "scripted", "display_name": "Scripted payments"}], "default": "scripted",
        }  # fmt: skip

    def test_with_none_on_the_list_is_empty(self, payments, signed_in_client, settings):
        settings.PAYMENT_GATEWAYS_ENABLED = []

        assert signed_in_client.get(GATEWAYS).json() == {"gateways": [], "default": None}

    def test_nothing_is_on_by_default(self, signed_in_client):
        assert signed_in_client.get(GATEWAYS).json() == {"gateways": [], "default": None}


class TestStartingAPayment:
    def test_it_makes_an_order_at_the_servers_price(self, payments, signed_in_client):
        response = make(signed_in_client, credits=250)

        body = response.json()
        assert response.status_code == 201
        assert (body["status"], body["amount_paise"], body["currency"], body["gateway"]) == (
            "pending",
            25000,
            "INR",
            "scripted",
        )
        assert body["plan"]["key"] == "one_time"
        assert body["credits"] == 250 and body["checkout"]["kind"] == "redirect"
        assert body["checkout"]["redirect_url"].endswith(f"/buy/return?order={body['id']}")
        assert PaymentOrder.objects.get().amount_paise == 25000

    def test_a_plan_is_priced_by_its_weeks_and_says_its_credits(self, payments, signed_in_client):
        body = signed_in_client.post(ORDERS, {"plan": "weekly_pro", "quantity": 2}, format="json").json()

        assert (body["amount_paise"], body["quantity"], body["credits"]) == (9800, 2, 200)

    def test_a_price_sent_by_the_client_is_not_read(self, payments, signed_in_client):
        body = make(signed_in_client, amount_paise=1, price=1, amount=1).json()

        assert body["amount_paise"] == 10000

    @pytest.mark.parametrize(
        ("body", "code"),
        [
            ({"plan": "platinum"}, "invalid_plan"),
            ({"plan": "one_time", "credits": 3}, "invalid_amount"),
            ({"plan": "one_time", "credits": 999999}, "invalid_amount"),
            ({"plan": "one_time"}, "invalid_amount"),
            ({"plan": "weekly_pro", "quantity": 99}, "invalid_amount"),
            ({"plan": "one_time", "credits": 100, "gateway": "stripe"}, "gateway_not_enabled"),
        ],
    )
    def test_what_will_not_be_sold_is_refused_and_nothing_is_made(self, payments, signed_in_client, body, code):
        response = signed_in_client.post(ORDERS, body, format="json")

        assert response.status_code == 400 and response.json()["code"] == code
        assert not PaymentOrder.objects.exists()

    def test_a_missing_plan_or_a_non_number_is_a_400_naming_the_field(self, payments, signed_in_client):
        assert "plan" in signed_in_client.post(ORDERS, {}, format="json").json()["fields"]
        assert (
            "credits"
            in signed_in_client.post(ORDERS, {"plan": "one_time", "credits": "lots"}, format="json").json()["fields"]
        )

    def test_the_fourth_waiting_payment_is_a_409(self, payments, signed_in_client):
        for _ in range(3):
            make(signed_in_client)

        response = make(signed_in_client)

        assert (response.status_code, response.json()["code"]) == (409, "too_many_pending")

    def test_a_full_queue_is_a_409(self, payments, signed_in_client, user):
        from credits.models import PlanPurchase
        from credits.plans.fulfilment import PlanFulfilment

        payments.buy("weekly_pro", quantity=12)
        PlanFulfilment().fulfil(PlanPurchase.objects.get())

        response = signed_in_client.post(ORDERS, {"plan": "weekly_pro", "quantity": 1}, format="json")

        assert (response.status_code, response.json()["code"]) == (409, "queue_full")

    def test_a_provider_that_is_down_is_a_502_and_nothing_is_granted(self, payments, signed_in_client, user):
        payments.script.checkout_error = GatewayUnavailable("down")

        response = make(signed_in_client)

        assert (response.status_code, response.json()["code"]) == (502, "gateway_unavailable")
        assert PaymentOrder.objects.get().status == "failed" and Ledger().balance(user) == 0

    def test_the_same_idempotency_key_makes_one_order(self, payments, signed_in_client):
        first = signed_in_client.post(
            ORDERS, {"plan": "one_time", "credits": 100}, format="json", HTTP_IDEMPOTENCY_KEY="k-1"
        )
        again = signed_in_client.post(
            ORDERS, {"plan": "one_time", "credits": 100}, format="json", HTTP_IDEMPOTENCY_KEY="k-1"
        )

        assert first.json()["id"] == again.json()["id"] and again["Idempotent-Replayed"] == "true"
        assert PaymentOrder.objects.count() == 1

    def test_it_is_rate_limited(self, payments, signed_in_client, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "payment_order", "2/min")

        statuses = [signed_in_client.post(ORDERS, {"plan": "platinum"}, format="json").status_code for _ in range(3)]

        assert statuses == [400, 400, 429]


class TestTheList:
    def test_it_holds_only_the_learners_own_newest_first(self, payments, signed_in_client, other_user):
        older = payments.buy()
        newer = payments.buy("weekly_pro")
        payments.buy(user=other_user)

        orders = signed_in_client.get(ORDERS).json()["orders"]

        assert [o["id"] for o in orders] == [str(newer.pk), str(older.pk)]
        assert "checkout" not in orders[0] and "provider_ref" not in orders[0]

    def test_a_learner_with_no_payments_has_an_empty_list(self, payments, signed_in_client):
        assert signed_in_client.get(ORDERS).json() == {"orders": []}


class TestTheOrderPage:
    def url(self, order):
        return f"{ORDERS}/{order.pk}"

    def test_it_is_private(self, payments, signed_in_client, other_user):
        order = payments.buy(user=other_user)

        assert signed_in_client.get(self.url(order)).status_code == 404

    def test_a_young_waiting_order_is_not_asked_about_and_grants_nothing(self, payments, signed_in_client, user):
        order = payments.buy("one_time", credits=100)
        payments.says_paid(order)  # the provider would say paid, but nobody asks yet

        body = signed_in_client.get(self.url(order)).json()

        assert body["status"] == "pending" and payments.script.status_calls == [] and Ledger().balance(user) == 0

    def test_the_return_alone_grants_nothing_whatever_it_claims(self, payments, signed_in_client, user):
        order = payments.buy("one_time", credits=100)

        response = signed_in_client.get(f"{self.url(order)}?paid=true&status=fulfilled&session_id=cs_1")

        assert response.json()["status"] == "pending" and Ledger().balance(user) == 0

    def test_an_older_order_makes_the_server_ask_and_a_paid_answer_grants(self, payments, signed_in_client, user):
        order = payments.buy("one_time", credits=100)
        PaymentOrder.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(seconds=45))
        payments.says_paid(order)

        body = signed_in_client.get(self.url(order)).json()

        assert body["status"] == "fulfilled" and body["fulfilled_at"] and Ledger().balance(user) == 100
        assert payments.script.status_calls == [order.provider_ref]

    def test_an_older_order_the_provider_says_is_still_waiting_stays_waiting(self, payments, signed_in_client, user):
        order = payments.buy()
        PaymentOrder.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=2))

        assert signed_in_client.get(self.url(order)).json()["status"] == "pending"
        assert Ledger().balance(user) == 0

    def test_an_unreachable_provider_changes_nothing(self, payments, signed_in_client):
        order = payments.buy()
        PaymentOrder.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=2))
        payments.script.status_error = GatewayUnavailable("down")

        response = signed_in_client.get(self.url(order))

        assert response.status_code == 200 and response.json()["status"] == "pending"

    def test_a_finished_order_is_not_asked_about_again(self, payments, signed_in_client):
        order = payments.buy()
        payments.send("succeeded", order)
        PaymentOrder.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(hours=1))

        signed_in_client.get(self.url(order))

        assert payments.script.status_calls == []

    def test_a_status_poll_is_rate_limited(self, payments, signed_in_client, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "payment_status", "2/min")
        order = payments.buy()

        statuses = [signed_in_client.get(self.url(order)).status_code for _ in range(3)]

        assert statuses == [200, 200, 429]

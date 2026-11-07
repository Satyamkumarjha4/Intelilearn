"""Unit under test: `/api/console/revenue` (`console.services.revenue.RevenueReport`; credits plan T31, §10): revenue
beside model cost, in rupees, with the rate used.

Why: whether Socra pays for itself is the question the money screens exist to answer, and it compares two currencies:
payments are in rupees and model calls are recorded in dollars. The comparison is only honest if the rate that turned
dollars into rupees is shown with it, the money is exact, and each figure counts only what happened in the range.

Use cases:
- paid is the sum of orders paid in the range (paid and fulfilled ones only), refunded is the sum of refund and dispute
  events applied in the range, net is the two apart; a refund of a payment from an earlier range counts in the range
  the refund happened in
- model cost is the sum of the calls in the range, in dollars as recorded and in rupees at `USD_INR_RATE`, and the rate
  is in the answer; what is left after model cost is net less that
- nothing in the range gives zeros, not an error; the range is the usage page's, and its other filters do not apply
- an event that took nothing back (ignored, or for an unknown order) is not a refund
- the money is exact to the paisa, and a refund counted once however many times it was said
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from payments.models import PaymentEventLog, PaymentOrder

pytestmark = pytest.mark.django_db

URL = "/api/console/revenue"


def paid(payments, now, credits=100, ago=timedelta(hours=1)):
    order = payments.buy("one_time", credits=credits)
    payments.send("succeeded", order)
    PaymentOrder.objects.filter(pk=order.pk).update(paid_at=now - ago)
    order.refresh_from_db()
    return order


def took_back(order, now, amount, kind="refunded", ago=timedelta(hours=1), outcome="applied", event_id=None):
    return PaymentEventLog.objects.create(
        gateway="scripted", event_id=event_id or f"e-{order.pk}-{amount}-{kind}", kind=kind, order=order,
        amount_paise=amount, outcome=outcome, received_at=now - ago,
    )  # fmt: skip


class TestTheFigures:
    def test_paid_refunded_and_net_for_the_range(self, staff_client, payments, now):
        first = paid(payments, now, 100)
        second = paid(payments, now, 250)
        took_back(first, now, 2500)
        took_back(second, now, 5000, kind="disputed")

        body = staff_client.get(f"{URL}?range=7d").json()

        assert body["orders"] == 2
        assert (body["paid"], body["refunded"], body["net"]) == ("350.00", "75.00", "275.00")

    def test_orders_and_refunds_outside_the_range_do_not_count(self, staff_client, payments, now):
        old = paid(payments, now, 100, ago=timedelta(days=20))
        took_back(old, now, 4000, ago=timedelta(days=2))  # a refund inside the range of a payment from before it

        body = staff_client.get(f"{URL}?range=7d").json()

        assert (body["paid"], body["refunded"], body["net"]) == ("0.00", "40.00", "-40.00")

    def test_an_order_that_never_paid_and_an_event_that_took_nothing_are_not_counted(self, staff_client, payments, now):
        waiting = payments.buy("one_time", credits=100)
        took_back(waiting, now, 9999, outcome="ignored")
        took_back(waiting, now, 9999, outcome="unknown_order", event_id="e2")
        took_back(waiting, now, 9999, kind="failed", event_id="e3")

        body = staff_client.get(URL).json()

        assert (body["orders"], body["paid"], body["refunded"]) == (0, "0.00", "0.00")

    def test_a_refund_said_twice_is_counted_once(self, staff_client, payments, now):
        order = paid(payments, now, 100)
        payments.send("refunded", order, amount=2500, event_id="evt_r")
        payments.send("refunded", order, amount=2500, event_id="evt_r")
        PaymentEventLog.objects.filter(kind="refunded").update(received_at=now - timedelta(hours=1))

        assert staff_client.get(URL).json()["refunded"] == "25.00"

    def test_nothing_at_all_gives_zeros(self, staff_client, now):
        body = staff_client.get(URL).json()

        assert (body["orders"], body["paid"], body["refunded"], body["net"]) == (0, "0.00", "0.00", "0.00")
        assert (body["model_cost"], body["after_model_cost"]) == ("0.00", "0.00")


class TestBesideModelCost:
    def test_the_cost_is_in_dollars_as_recorded_and_in_rupees_at_the_rate_shown(
        self, staff_client, payments, now, make_call, settings
    ):
        settings.USD_INR_RATE = Decimal("85")
        paid(payments, now, 200)
        make_call(cost=Decimal("0.5"))
        make_call(cost=Decimal("0.25"), provider_key="groq", model_name="m")

        body = staff_client.get(URL).json()

        assert body["model_cost_usd"] == "0.7500" and body["model_cost"] == "63.75"
        assert body["usd_inr_rate"] == "85" and body["after_model_cost"] == "136.25"  # 200 - 63.75

    def test_a_different_rate_changes_the_rupees_and_says_which_it_used(self, staff_client, now, make_call, settings):
        settings.USD_INR_RATE = Decimal("90.5")
        make_call(cost=Decimal("1"))

        body = staff_client.get(URL).json()

        assert (body["model_cost"], body["usd_inr_rate"]) == ("90.50", "90.5")

    def test_cost_outside_the_range_is_left_out_and_the_usage_filters_do_not_apply(self, staff_client, now, make_call):
        make_call(cost=Decimal("1"), ago=timedelta(days=20))
        make_call(cost=Decimal("2"), provider_key="groq", model_name="m")

        body = staff_client.get(f"{URL}?range=7d&provider=gemini").json()

        assert body["model_cost_usd"] == "2.0000"

    def test_the_money_is_exact_to_the_paisa(self, staff_client, payments, now):
        order = paid(payments, now, 33)  # 3300 paise
        took_back(order, now, 1)

        body = staff_client.get(URL).json()

        assert (body["paid"], body["refunded"], body["net"]) == ("33.00", "0.01", "32.99")

    def test_the_range_is_named_and_a_custom_one_works(self, staff_client, now):
        assert staff_client.get(f"{URL}?range=30d").json()["range"] == "30d"
        custom = staff_client.get(f"{URL}?range=custom&start=2026-03-01&end=2026-03-10")
        assert custom.status_code == 200 and custom.json()["range"] == "custom"

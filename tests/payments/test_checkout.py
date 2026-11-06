"""Unit under test: `payments.checkout.CheckoutService` (credits plan §5.8, T20, §11).

Why: this is where a learner's click becomes a payment, so it is where a client must not be able to name a price, pay
through a provider that is switched off, or pile up orders. And when the provider is down the learner must be told
plainly, with nothing charged, nothing granted and no order left waiting.

Use cases:
- one-time credits and a plan become a pending order with the server's amount (from the plan table, in paise), the
  gateway's reference and checkout, a deadline, and a purchase that is pending: nothing is granted
- the gateway is asked with the order's id, the amount, the plan's name, the buyer's email and return links to the site
- a plan that is not offered, or an amount or a number of weeks that is not allowed, is refused and makes nothing
- a gateway that is not switched on is refused whatever the client names, and with none on buying is not open
- at most three payments may be waiting; failed and paid ones do not count; the limit is the credit settings'
- a plan queue that is full is refused before any payment is asked for
- a provider that cannot be reached leaves the order failed and its purchase void, grants nothing, and says so
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from credits.ledger import Ledger
from credits.models import CreditSettings, PlanPurchase
from credits.plans.errors import InvalidPlanRequest, QueueFull
from payments.checkout import CheckoutService
from payments.errors import GatewayDown, GatewayNotEnabled, GatewayUnavailable, TooManyPending
from payments.models import PaymentOrder

pytestmark = pytest.mark.django_db


class TestAnOrder:
    def test_one_time_credits_are_priced_from_the_plan_table(self, payments, user):
        order = payments.buy("one_time", credits=250)

        assert (order.amount_paise, order.currency, order.status, order.gateway) == (
            25000,
            "INR",
            "pending",
            "scripted",
        )
        assert order.provider_ref == f"ref_{order.pk}"
        assert order.checkout == {"kind": "redirect", "redirect_url": f"http://shop.test/buy/return?order={order.pk}"}
        assert order.purchase.status == PlanPurchase.Status.PENDING and order.purchase.credits == 250

    def test_a_plan_is_priced_by_its_weeks(self, payments):
        order = payments.buy("weekly_pro", quantity=3)

        assert order.amount_paise == 3 * 4900 and order.purchase.quantity == 3

    def test_nothing_is_granted_by_starting_a_payment(self, payments, user):
        payments.buy("one_time", credits=100)

        assert Ledger().balance(user) == 0 and not PaymentOrder.objects.filter(status="fulfilled").exists()

    def test_the_order_has_a_deadline_a_day_out(self, payments):
        order = payments.buy()

        assert timedelta(hours=23) < order.expires_at - timezone.now() <= timedelta(hours=24)

    def test_the_gateway_is_asked_about_this_order_and_this_buyer(self, payments, user):
        order = payments.buy("monthly_pro")

        asked, urls = payments.script.checkouts[0]
        assert (asked.order_id, asked.amount_paise, asked.currency) == (str(order.pk), 19900, "INR")
        assert (asked.description, asked.buyer_email) == ("Monthly Pro", user.email)
        assert urls.success == f"http://shop.test/buy/return?order={order.pk}"
        assert urls.cancel == f"http://shop.test/buy/return?order={order.pk}&cancelled=1"


class TestWhatIsRefused:
    @pytest.mark.parametrize(
        ("plan", "kwargs", "code"),
        [
            ("platinum", {}, "invalid_plan"),
            ("one_time", {"credits": 9}, "invalid_amount"),
            ("one_time", {"credits": 5001}, "invalid_amount"),
            ("one_time", {}, "invalid_amount"),
            ("weekly_pro", {"quantity": 13}, "invalid_amount"),
            ("weekly_pro", {"quantity": 0}, "invalid_amount"),
        ],
    )
    def test_a_purchase_the_server_will_not_sell_makes_no_order(self, payments, plan, kwargs, code):
        with pytest.raises(InvalidPlanRequest) as refused:
            CheckoutService().start(payments.user, plan, **kwargs)

        assert refused.value.code == code
        assert not PaymentOrder.objects.exists() and not PlanPurchase.objects.exists()

    def test_a_gateway_that_is_not_on_is_refused(self, payments):
        with pytest.raises(GatewayNotEnabled):
            CheckoutService().start(payments.user, "one_time", credits=100, gateway="stripe")

        assert not PaymentOrder.objects.exists()

    def test_with_no_gateway_on_buying_is_not_open(self, payments, settings):
        settings.PAYMENT_GATEWAYS_ENABLED = []

        with pytest.raises(GatewayNotEnabled):
            CheckoutService().start(payments.user, "one_time", credits=100)

    def test_a_full_queue_is_refused_before_anything_is_asked_of_the_provider(self, payments):
        payments.buy("weekly_pro", quantity=12)
        PaymentOrder.objects.update(status="fulfilled")  # paid and fulfilled: its 12 weeks are open
        from credits.plans.fulfilment import PlanFulfilment

        PlanFulfilment().fulfil(PlanPurchase.objects.get())
        before = len(payments.script.checkouts)

        with pytest.raises(QueueFull):
            payments.buy("weekly_pro", quantity=1)

        assert len(payments.script.checkouts) == before and PaymentOrder.objects.count() == 1


class TestTooManyWaiting:
    def test_the_fourth_waiting_payment_is_refused(self, payments):
        for _ in range(3):
            payments.buy()

        with pytest.raises(TooManyPending):
            payments.buy()

        assert PaymentOrder.objects.count() == 3

    def test_only_waiting_payments_count(self, payments):
        orders = [payments.buy() for _ in range(3)]
        PaymentOrder.objects.filter(pk=orders[0].pk).update(status="failed")
        PaymentOrder.objects.filter(pk=orders[1].pk).update(status="fulfilled")

        assert payments.buy().status == "pending"

    def test_the_limit_is_the_credit_settings(self, payments):
        CreditSettings.objects.update_or_create(pk=1, defaults={"max_pending_orders": 1})
        payments.buy()

        with pytest.raises(TooManyPending):
            payments.buy()

    def test_another_learners_payments_do_not_count(self, payments, other_user):
        for _ in range(3):
            payments.buy(user=other_user)

        assert payments.buy().status == "pending"


class TestAProviderThatIsDown:
    def test_the_order_fails_its_purchase_is_void_and_nothing_is_granted(self, payments, user):
        payments.script.checkout_error = GatewayUnavailable("down")

        with pytest.raises(GatewayDown) as down:
            payments.buy()

        order = PaymentOrder.objects.get()
        assert down.value.default_code == "gateway_unavailable"
        assert (order.status, order.failure_reason, order.provider_ref) == ("failed", "gateway_unavailable", "")
        assert order.purchase.status == PlanPurchase.Status.VOID and Ledger().balance(user) == 0

    def test_a_failed_attempt_does_not_use_up_a_waiting_place(self, payments):
        payments.script.checkout_error = GatewayUnavailable("down")
        for _ in range(5):
            with pytest.raises(GatewayDown):
                payments.buy()
        payments.script.checkout_error = None

        assert payments.buy().status == "pending"

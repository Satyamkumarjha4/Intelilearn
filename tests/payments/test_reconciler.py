"""Unit under test: `payments.reconcile.OrderReconciler` and the `payments.reconcile` task (credits plan §5.9, T24).

Why: a webhook can be late or never arrive, and a browser coming back from the provider proves nothing. So the server
asks the provider, and what it hears goes through exactly the path a webhook takes. A payment must never be lost to a
missed callback, and never granted twice because both the callback and the job heard of it.

Use cases:
- a waiting order older than 15 minutes is asked about; a paid answer fulfils it, a failed or expired answer fails it, a
  still-waiting answer leaves it; a younger order is not asked about
- the same answer twice, or a webhook after the job, grants once
- an answer whose amount or currency does not match grants nothing
- an order past its deadline that is still unpaid is let go (expired, its purchase void); before its deadline it is not
- an order whose checkout was never made is failed after a while
- a paid order that was never fulfilled is fulfilled by the job
- a provider that cannot be reached, or whose keys are gone, changes nothing; one switched off since is still asked
- the task is thin: it runs the reconciler and reports counts, and it is on the beat schedule every five minutes
"""

from datetime import timedelta

import pytest
from celery import current_app  # noqa: F401  (the app must be loaded for the schedule)
from django.utils import timezone

from credits.ledger import Ledger
from credits.models import PlanPurchase
from payments.errors import GatewayUnavailable
from payments.models import PaymentEventLog, PaymentOrder
from payments.reconcile import OrderReconciler
from payments.tasks import reconcile

pytestmark = pytest.mark.django_db


def aged(order, minutes):
    PaymentOrder.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=minutes))
    order.refresh_from_db()


class TestAskingTheProvider:
    def test_a_paid_answer_fulfils_the_order(self, payments, user):
        order = payments.buy("one_time", credits=100)
        aged(order, 20)
        payments.says_paid(order)

        report = OrderReconciler().run()

        order.refresh_from_db()
        assert order.status == "fulfilled" and Ledger().balance(user) == 100
        assert (report.asked, report.settled) == (1, 1) and payments.script.status_calls == [order.provider_ref]
        assert PaymentEventLog.objects.get().event_id == f"status:{order.pk}:succeeded"

    @pytest.mark.parametrize("state", ["failed", "expired"])
    def test_a_failed_or_expired_answer_fails_the_order(self, payments, user, state):
        order = payments.buy()
        aged(order, 20)
        payments.says(order, state)

        OrderReconciler().run()

        order.refresh_from_db()
        assert order.status == "failed" and order.purchase.status == PlanPurchase.Status.VOID

    def test_a_still_waiting_answer_leaves_the_order(self, payments, user):
        order = payments.buy()
        aged(order, 20)

        report = OrderReconciler().run()

        order.refresh_from_db()
        assert order.status == "pending" and (report.asked, report.settled, report.expired) == (1, 0, 0)

    def test_a_younger_order_is_not_asked_about(self, payments):
        order = payments.buy()
        aged(order, 5)
        payments.says_paid(order)

        report = OrderReconciler().run()

        assert report.asked == 0 and payments.script.status_calls == []

    def test_a_second_run_changes_nothing(self, payments, user):
        order = payments.buy("one_time", credits=100)
        aged(order, 20)
        payments.says_paid(order)
        OrderReconciler().run()

        again = OrderReconciler().run()

        assert again.asked == 0 and Ledger().balance(user) == 100

    def test_a_webhook_after_the_job_grants_nothing_more(self, payments, user):
        order = payments.buy("one_time", credits=100)
        aged(order, 20)
        payments.says_paid(order)
        OrderReconciler().run()

        [applied] = payments.send("succeeded", order)

        assert applied.outcome == "ignored" and Ledger().balance(user) == 100

    def test_an_answer_for_another_amount_grants_nothing(self, payments, user):
        order = payments.buy("one_time", credits=100)
        aged(order, 20)
        payments.says_paid(order, amount=1)

        OrderReconciler().run()

        order.refresh_from_db()
        assert order.status == "pending" and Ledger().balance(user) == 0
        assert PaymentEventLog.objects.get().outcome == "amount_mismatch"

    def test_a_provider_that_cannot_be_reached_changes_nothing(self, payments, user):
        order = payments.buy()
        aged(order, 20)
        payments.script.status_error = GatewayUnavailable("down")

        report = OrderReconciler().run()

        order.refresh_from_db()
        assert order.status == "pending" and report.settled == 0

    def test_an_order_of_a_gateway_switched_off_since_is_still_asked_about(self, payments, user, settings):
        order = payments.buy("one_time", credits=100)
        aged(order, 20)
        payments.says_paid(order)
        settings.PAYMENT_GATEWAYS_ENABLED = []

        OrderReconciler().run()

        assert Ledger().balance(user) == 100


class TestLettingGo:
    def test_an_unpaid_order_past_its_deadline_expires_and_its_purchase_is_void(self, payments, user):
        order = payments.buy()
        aged(order, 60 * 25)
        PaymentOrder.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(hours=1))

        report = OrderReconciler().run()

        order.refresh_from_db()
        assert order.status == "expired" and report.expired == 1
        assert order.purchase.status == PlanPurchase.Status.VOID

    def test_before_its_deadline_it_is_left_waiting(self, payments):
        order = payments.buy()
        aged(order, 60)

        OrderReconciler().run()

        order.refresh_from_db()
        assert order.status == "pending"

    def test_an_expired_order_that_was_paid_after_all_still_grants(self, payments, user):
        order = payments.buy("one_time", credits=100)
        aged(order, 60 * 25)
        PaymentOrder.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        OrderReconciler().run()

        payments.send("succeeded", order)

        assert Ledger().balance(user) == 100

    def test_an_order_whose_checkout_was_never_made_is_failed(self, payments, user):
        order = payments.buy()
        PaymentOrder.objects.filter(pk=order.pk).update(
            status="created", provider_ref="", created_at=timezone.now() - timedelta(minutes=30)
        )

        OrderReconciler().run()

        order.refresh_from_db()
        assert order.status == "failed" and order.failure_reason == "checkout_not_made"


class TestAStuckPaidOrder:
    def test_the_job_fulfils_it(self, payments, user):
        order = payments.buy("one_time", credits=100)
        PaymentOrder.objects.filter(pk=order.pk).update(status="paid", paid_at=timezone.now())

        report = OrderReconciler().run()

        order.refresh_from_db()
        assert order.status == "fulfilled" and report.retried == 1 and Ledger().balance(user) == 100


class TestTheTask:
    def test_it_runs_the_reconciler_and_reports_counts(self, payments):
        order = payments.buy()
        aged(order, 20)

        assert reconcile() == {"asked": 1, "settled": 0, "retried": 0, "expired": 0}

    def test_it_runs_every_five_minutes_on_beat(self, settings):
        assert settings.CELERY_BEAT_SCHEDULE["payments.reconcile"] == {"task": "payments.reconcile", "schedule": 300.0}

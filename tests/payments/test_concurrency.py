"""Unit under test: `OrderEvents` and `OrderReconciler` with several real threads (and so several database
connections) at once (credits plan §11, §13.3).

Why: a provider retries a webhook while it is still being handled, and the five-minute job can ask about an order at the
very moment its callback arrives. The order row lock and the unique event row are the whole defence against granting
twice, and a single thread cannot tell them from nothing. So these use real threads and real transactions, released
together by a barrier, and check what must hold in every interleaving.

Use cases:
- the same event sent by several threads at once is applied once and the rest are duplicates (or ignored): the credits
  are granted once
- the same event for an order nobody knows, at once (nothing to lock, so both reach the unique event row): one is
  recorded and the other is a duplicate, and neither fails
- a webhook and the reconciler's answer for the same payment, at once, grant once
- a success and a refund at once leave the books balanced
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connections
from django.db.models.signals import pre_save
from django.utils import timezone

from credits.audit import LedgerAudit
from credits.ledger import Ledger
from credits.models import CreditTransaction
from payments.events import OrderEvents
from payments.gateway import PaymentEvent
from payments.models import PaymentEventLog, PaymentOrder
from payments.reconcile import OrderReconciler

pytestmark = pytest.mark.django_db(transaction=True)


def together(jobs):
    barrier = threading.Barrier(len(jobs))

    def run(job):
        try:
            barrier.wait(timeout=30)
            return job()
        except Exception as exc:  # the test looks at what each thread got
            return exc
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return list(pool.map(run, jobs))


def event_for(order, kind="succeeded", event_id="evt_1", amount=None):
    return PaymentEvent(
        event_id,
        kind,
        order.provider_ref,
        order.amount_paise if amount is None else amount,
        "INR",
        datetime.now(UTC),
        "pay_1",
    )


def test_the_same_event_for_an_unknown_order_at_once_is_recorded_once_and_neither_fails(payments, user):
    order = payments.buy("one_time", credits=100)
    order.provider_ref = "ref_nobody"  # there is no order to lock, so only the unique event row separates the two
    event = event_for(order, event_id="evt_unknown")

    def pause(**_):
        time.sleep(0.3)  # both have looked for the event and found none before either writes it

    pre_save.connect(pause, sender=PaymentEventLog)
    try:
        results = together([lambda: OrderEvents().apply("scripted", event) for _ in range(2)])
    finally:
        pre_save.disconnect(pause, sender=PaymentEventLog)

    assert not [r for r in results if isinstance(r, Exception)], results
    assert sorted(r.outcome for r in results) == ["duplicate", "unknown_order"]
    assert PaymentEventLog.objects.filter(event_id="evt_unknown").count() == 1


def test_the_same_event_at_once_is_applied_once(payments, user):
    order = payments.buy("one_time", credits=100)
    event = event_for(order)

    results = together([lambda: OrderEvents().apply("scripted", event) for _ in range(6)])

    assert not [r for r in results if isinstance(r, Exception)], results
    assert sorted(r.outcome for r in results).count("applied") == 1
    assert Ledger().balance(user) == 100 and CreditTransaction.objects.filter(user=user, type="grant").count() == 1
    assert PaymentEventLog.objects.count() == 1 and PaymentOrder.objects.get().status == "fulfilled"
    assert LedgerAudit().check(user).ok


def test_a_webhook_and_the_reconciler_at_once_grant_once(payments, user):
    order = payments.buy("one_time", credits=100)
    PaymentOrder.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=30))
    order.refresh_from_db()
    payments.says_paid(order)
    event = event_for(order, event_id="evt_webhook")

    results = together(
        [
            lambda: OrderEvents().apply("scripted", event),
            lambda: OrderReconciler().run(),
            lambda: OrderReconciler().refresh(order),
        ]
    )

    assert not [r for r in results if isinstance(r, Exception)], results
    assert Ledger().balance(user) == 100 and CreditTransaction.objects.filter(user=user, type="grant").count() == 1
    assert PaymentOrder.objects.get().status == "fulfilled"
    assert LedgerAudit().check(user).ok


def test_a_success_and_a_refund_at_once_leave_the_books_balanced(payments, user):
    order = payments.buy("one_time", credits=100)
    PaymentOrder.objects.filter(pk=order.pk).update(status="paid", paid_at=timezone.now())

    results = together(
        [
            lambda: OrderEvents().apply("scripted", event_for(order, "succeeded", "evt_s")),
            lambda: OrderEvents().apply("scripted", event_for(order, "refunded", "evt_r")),
        ]
    )

    assert not [r for r in results if isinstance(r, Exception)], results
    assert Ledger().balance(user) in (0, 100) and LedgerAudit().check(user).ok
    assert PaymentOrder.objects.get().status == "fulfilled"

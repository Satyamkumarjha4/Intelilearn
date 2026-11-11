"""Unit under test: `payments.events.OrderEvents` and `WebhookProcessor`, with `FulfilmentService`,
`ClawbackService` and `OrderLifecycle` (credits plan §5.8, T22, T23, T32, §11, §13.3).

Why: this is the money. A payment that was made must give the credits exactly once however the news arrives (a webhook,
its retry, a late one, the five-minute job), a payment that was not made, or was made for another amount, must give
nothing, and a refund must take back only what is still unspent, never going below zero. The rules are the state machine
of an order and they are tested on every path.

Use cases:
- a signed success event makes the order paid and fulfilled in one step: the credits are in the wallet, the event row
  says `applied`, and the purchase and the order agree
- the same event again (a provider's retry), and the same success under another event id, grant once
- an event for an order we never made is recorded as `unknown_order` and changes nothing
- an amount or a currency that does not match the order is recorded as `amount_mismatch`, grants nothing, and is logged
- a success that arrives after the order expired or failed still grants (the money was taken), and revives its void
  purchase
- fulfilling an order that is already fulfilled changes nothing and grants nothing more, and fulfilling one that was
  never paid is refused and grants nothing
- a failure event ends a waiting order and voids its purchase; after a payment it changes nothing
- a plan order grants its first week at once and queues the rest
- a full refund takes back every unspent credit of the purchase and revokes its emptied bucket; a partial refund takes
  its share, and the parts add up to the whole; credits already spent are a shortfall, recorded on the event and the
  ledger row; a wallet is never taken below zero; credits from elsewhere are untouched
- a refund of a plan takes back unstarted weeks first (they hold nothing yet), then the running week's unspent credits
- a refund of more than was paid, in another currency, or for an order never paid is not applied
- a dispute takes the money back like a refund does
- a refunded reserve that is released later does not put the credits back (a revoked bucket stays empty)
- the ledger equals the buckets after all of it
"""

import logging
from datetime import timedelta

import pytest
from django.utils import timezone
from support.clock import FakeClock

from credits.audit import LedgerAudit
from credits.ledger import Ledger
from credits.models import CreditBucket, CreditTransaction, PlanPeriod, PlanPurchase
from payments.fulfilment import FulfilmentService
from payments.models import PaymentEventLog, PaymentOrder

pytestmark = pytest.mark.django_db


def outcomes():
    return list(PaymentEventLog.objects.order_by("id").values_list("kind", "outcome"))


def sound(user):
    assert LedgerAudit().check(user).ok


class TestAPayment:
    def test_a_success_grants_the_credits_once_and_closes_the_order(self, payments, user):
        order = payments.buy("one_time", credits=250)

        [applied] = payments.send("succeeded", order)

        order.refresh_from_db()
        assert applied.outcome == "applied" and order.status == "fulfilled"
        assert order.paid_at and order.fulfilled_at and order.payment_ref == "pay_1"
        assert order.purchase.status == PlanPurchase.Status.FULFILLED
        assert Ledger().balance(user) == 250
        assert CreditBucket.objects.get(user=user).purchase_id == order.purchase_id
        assert outcomes() == [("succeeded", "applied")]
        sound(user)

    def test_the_same_event_again_changes_nothing(self, payments, user):
        order = payments.buy("one_time", credits=100)
        payments.send("succeeded", order, event_id="evt_x")

        [again] = payments.send("succeeded", order, event_id="evt_x")

        assert again.outcome == "duplicate" and Ledger().balance(user) == 100
        assert PaymentEventLog.objects.count() == 1 and CreditTransaction.objects.filter(type="grant").count() == 1

    def test_the_same_success_under_another_event_id_grants_once(self, payments, user):
        order = payments.buy("one_time", credits=100)
        payments.send("succeeded", order, event_id="evt_1")

        [second] = payments.send("succeeded", order, event_id="evt_2")

        assert second.outcome == "ignored" and Ledger().balance(user) == 100
        assert outcomes() == [("succeeded", "applied"), ("succeeded", "ignored")]

    def test_a_plan_grants_its_first_week_at_once_and_queues_the_rest(self, payments, user):
        order = payments.buy("weekly_pro", quantity=3)

        payments.send("succeeded", order)

        assert Ledger().balance(user) == 100
        assert list(PlanPeriod.objects.filter(user=user).order_by("position").values_list("status", flat=True)) == [
            "active", "queued", "queued",
        ]  # fmt: skip

    def test_an_event_for_an_order_we_never_made_is_only_recorded(self, payments, user):
        order = payments.buy()
        PaymentOrder.objects.filter(pk=order.pk).update(provider_ref="someone-elses")
        order.provider_ref = "ref_unknown"

        [applied] = payments.send("succeeded", order)

        assert applied.outcome == "unknown_order" and Ledger().balance(user) == 0
        assert PaymentEventLog.objects.get().order is None


class TestFulfilmentItself:
    def test_an_order_already_fulfilled_is_returned_as_it_is_and_grants_nothing_more(self, payments, user):
        order = payments.buy("one_time", credits=100)
        payments.send("succeeded", order)
        order.refresh_from_db()
        assert order.status == "fulfilled" and Ledger().balance(user) == 100
        rows = CreditTransaction.objects.count()

        again = FulfilmentService().fulfil(order)

        assert again.status == "fulfilled" and Ledger().balance(user) == 100
        assert CreditTransaction.objects.count() == rows

    def test_an_order_that_was_never_paid_is_refused_and_grants_nothing(self, payments, user):
        order = payments.buy("one_time", credits=100)

        with pytest.raises(ValueError, match="pending order cannot be fulfilled"):
            FulfilmentService().fulfil(order)

        order.refresh_from_db()
        assert order.status == "pending" and Ledger().balance(user) == 0
        assert not CreditTransaction.objects.filter(user=user).exists()


class TestAWrongAmount:
    @pytest.mark.parametrize(
        ("amount", "currency"), [(9999, "INR"), (10000 - 1, "INR"), (10000, "USD"), (10001, "INR")]
    )
    def test_nothing_is_granted_and_it_is_logged(self, payments, user, caplog, amount, currency):
        order = payments.buy("one_time", credits=100)

        with caplog.at_level(logging.ERROR, logger="payments.events"):
            [applied] = payments.send("succeeded", order, amount=amount, currency=currency)

        order.refresh_from_db()
        assert applied.outcome == "amount_mismatch" and order.status == "pending" and Ledger().balance(user) == 0
        assert PaymentEventLog.objects.get().outcome == "amount_mismatch"
        assert any("Nothing was granted" in record.message for record in caplog.records)

    def test_the_right_event_afterwards_still_works(self, payments, user):
        order = payments.buy("one_time", credits=100)
        payments.send("succeeded", order, amount=1, event_id="bad")

        payments.send("succeeded", order, event_id="good")

        assert Ledger().balance(user) == 100


class TestALatePayment:
    @pytest.mark.parametrize("ended", ["expired", "failed"])
    def test_money_that_was_taken_is_honoured(self, payments, user, ended):
        order = payments.buy("one_time", credits=100)
        PaymentOrder.objects.filter(pk=order.pk).update(status=ended)
        PlanPurchase.objects.filter(pk=order.purchase_id).update(status="void")

        [applied] = payments.send("succeeded", order)

        order.refresh_from_db()
        assert applied.outcome == "applied" and order.status == "fulfilled" and Ledger().balance(user) == 100
        assert order.purchase.status == PlanPurchase.Status.FULFILLED
        sound(user)


class TestAFailure:
    def test_a_waiting_order_fails_and_its_purchase_is_void(self, payments, user):
        order = payments.buy()

        [applied] = payments.send("failed", order)

        order.refresh_from_db()
        assert applied.outcome == "applied" and order.status == "failed" and order.failure_reason == "payment_failed"
        assert order.purchase.status == PlanPurchase.Status.VOID and Ledger().balance(user) == 0

    def test_after_a_payment_it_changes_nothing(self, payments, user):
        order = payments.buy("one_time", credits=100)
        payments.send("succeeded", order)

        [applied] = payments.send("failed", order)

        order.refresh_from_db()
        assert applied.outcome == "ignored" and order.status == "fulfilled" and Ledger().balance(user) == 100


class TestRefunds:
    def bought(self, payments, credits=100):
        order = payments.buy("one_time", credits=credits)
        payments.send("succeeded", order)
        return order

    def test_a_full_refund_takes_back_everything_unspent_and_revokes_the_bucket(self, payments, user):
        order = self.bought(payments)

        [applied] = payments.send("refunded", order)

        order.refresh_from_db()
        bucket = CreditBucket.objects.get(user=user)
        assert applied.outcome == "applied" and applied.shortfall == 0 and order.refunded_paise == order.amount_paise
        assert order.status == "fulfilled"  # a refund does not change the state
        assert (bucket.amount_remaining, bucket.revoked_at is not None) == (0, True) and Ledger().balance(user) == 0
        sound(user)

    def test_a_partial_refund_takes_its_share_and_the_parts_add_up_to_the_whole(self, payments, user):
        order = self.bought(payments, credits=100)

        payments.send("refunded", order, amount=2500)
        assert Ledger().balance(user) == 75
        payments.send("refunded", order, amount=2500)
        assert Ledger().balance(user) == 50
        payments.send("refunded", order, amount=5000)

        order.refresh_from_db()
        assert Ledger().balance(user) == 0 and order.refunded_paise == 10000
        sound(user)

    def test_odd_amounts_still_add_up_exactly(self, payments, user):
        order = self.bought(payments, credits=10)  # 1000 paise
        for paise in (333, 333, 334):
            payments.send("refunded", order, amount=paise)

        assert Ledger().balance(user) == 0

    def test_credits_already_spent_are_a_shortfall_and_the_wallet_never_goes_below_zero(self, payments, user):
        order = self.bought(payments, credits=100)
        Ledger().debit(user, 70, "lesson.create", "spent-1")

        [applied] = payments.send("refunded", order)

        assert applied.outcome == "applied" and applied.shortfall == 70 and Ledger().balance(user) == 0
        assert PaymentEventLog.objects.get(kind="refunded").shortfall == 70
        row = CreditTransaction.objects.get(type="refund")
        assert (row.amount, row.meta["shortfall"], row.meta["order"]) == (-30, 70, str(order.pk))
        sound(user)

    def test_credits_from_elsewhere_are_untouched(self, payments, user):
        Ledger().grant(user, "signup", 30, "signup:1")
        order = self.bought(payments, credits=100)
        Ledger().debit(user, 120, "x", "spent-1")  # spends the signup credits too

        payments.send("refunded", order)

        assert Ledger().balance(user) == 10  # 130 - 120 spent = 10 left; what was refunded came from the purchase only
        sound(user)

    def test_a_reserve_released_after_a_refund_does_not_put_the_credits_back(self, payments, user, credits_on):
        order = self.bought(payments, credits=10)
        ledger = Ledger()
        held = ledger.place_hold(user, 10, "lesson.create", "hold-1", subject_id=order.pk)

        payments.send("refunded", order)
        ledger.release(held.hold.pk, "release-1")

        assert ledger.balance(user) == 0
        sound(user)

    def test_a_refund_of_more_than_was_paid_or_in_another_currency_is_not_applied(self, payments, user):
        order = self.bought(payments)

        over = payments.send("refunded", order, amount=order.amount_paise + 1)[0]
        other = payments.send("refunded", order, currency="USD")[0]

        assert (over.outcome, other.outcome) == ("amount_mismatch", "amount_mismatch") and Ledger().balance(user) == 100

    def test_a_refund_for_an_order_never_paid_is_ignored(self, payments, user):
        order = payments.buy()

        [applied] = payments.send("refunded", order)

        assert applied.outcome == "ignored" and PaymentOrder.objects.get().refunded_paise == 0

    def test_refunding_past_the_whole_takes_only_what_is_left(self, payments, user):
        order = self.bought(payments)
        payments.send("refunded", order)

        [again] = payments.send("refunded", order, amount=1)

        assert again.outcome == "ignored" and PaymentOrder.objects.get().refunded_paise == order.amount_paise

    def test_a_dispute_takes_the_money_back_like_a_refund(self, payments, user):
        order = self.bought(payments)

        [applied] = payments.send("disputed", order)

        assert applied.outcome == "applied" and Ledger().balance(user) == 0
        assert PaymentOrder.objects.get().refunded_paise == order.amount_paise

    def test_a_refund_after_a_dispute_for_the_rest_takes_nothing_twice(self, payments, user):
        order = self.bought(payments)
        payments.send("disputed", order)

        [again] = payments.send("refunded", order, event_id="evt_late")

        assert again.outcome == "ignored" and Ledger().balance(user) == 0


class TestRefundingAPlan:
    def test_unstarted_weeks_are_cancelled_first_then_the_running_weeks_unspent_credits(self, payments, user):
        order = payments.buy("weekly_pro", quantity=4)  # 400 credits in all: 100 now, 300 queued
        payments.send("succeeded", order)
        Ledger().debit(user, 40, "lesson.create", "spent-1")  # 60 of the running week's 100 are left

        payments.send("refunded", order, amount=order.amount_paise // 2)  # half: 200 credits

        periods = list(PlanPeriod.objects.filter(user=user).order_by("position").values_list("status", flat=True))
        assert periods == [
            "active",
            "queued",
            "ended",
            "ended",
        ]  # the last two weeks (200) cancelled; nothing taken yet
        assert Ledger().balance(user) == 60

    def test_the_rest_comes_out_of_the_running_week(self, payments, user):
        order = payments.buy("weekly_pro", quantity=2)  # 200: 100 now, 100 queued
        payments.send("succeeded", order)

        payments.send("refunded", order)  # all 200

        assert PlanPeriod.objects.filter(user=user).order_by("position").last().status == "ended"
        assert Ledger().balance(user) == 0
        sound(user)

    def test_a_refund_does_not_end_a_week_it_cannot_cover_whole(self, payments, user):
        order = payments.buy("weekly_pro", quantity=2)
        payments.send("succeeded", order)

        payments.send("refunded", order, amount=order.amount_paise // 4)  # 50 credits: less than a queued week

        assert PlanPeriod.objects.filter(user=user, status="queued").count() == 1 and Ledger().balance(user) == 50

    def test_a_cancelled_week_never_starts(self, payments, user):
        order = payments.buy("weekly_pro", quantity=2)
        payments.send("succeeded", order)
        payments.send("refunded", order)

        ledger = Ledger(clock=FakeClock(timezone.now() + timedelta(days=30)))
        ledger.activate_periods(user)

        assert ledger.balance(user) == 0 and not CreditBucket.objects.filter(user=user, amount_remaining__gt=0).exists()

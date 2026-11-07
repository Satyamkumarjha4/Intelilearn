"""Unit under test: `payments.refund_reconcile.RefundReconciler`, the sweep that asks a provider about refunds an
administrator asked for and has not heard back about, and `RefundDesk.mark_failed` (credits plan D14; phase 10.9
step 0).

Why: a refund is asked for now and done later, sometimes days later, and may fail (an old payment, a closed bank
account). The provider says so in a webhook that can be late or lost. Until it is known, the amount asked for counts as
spoken for, so nobody asks twice; once it is known to have failed, that amount must be free to ask for again, and once
it is known to have gone through, the credits must come back exactly as a webhook would have brought them, once. A
provider that cannot be asked at all is the one case where a person says it failed.

Use cases:
- a waiting refund older than the wait is asked about; one the provider says is processed brings the credits back and
  becomes confirmed, and the webhook for it arriving afterwards changes nothing more
- one the provider says failed becomes failed, and the amount it held is free to ask for again
- one the provider says is still pending is left as it is, and so is one asked about too recently
- a gateway that cannot answer, and a provider that cannot be reached, leave it waiting (counted, not an error)
- attempts already confirmed or failed are not asked about again
- the five-minute payments task runs it, with its own report left out of the task's counts
- `mark_failed` is for an attempt whose gateway cannot answer: it marks it failed, frees the amount, and writes the
  change-log entry; it refuses an attempt a provider can still be asked about, one that is not waiting, and does nothing
  for a confirmed one
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from console.models import AuditEntry
from credits.ledger import Ledger
from payments.errors import GatewayUnavailable, NotSupported
from payments.gateway import RefundStatus
from payments.models import PaymentEventLog, PaymentOrder, RefundAttempt
from payments.refund_reconcile import RefundReconciler
from payments.refunds import RefundDesk, RefundNotMarkable
from payments.registry import PaymentGateways
from payments.tasks import reconcile

pytestmark = pytest.mark.django_db


@pytest.fixture
def answers(payments, monkeypatch):
    """The scripted gateway made able to answer about refunds: `answers[ref]` is a `RefundStatus` or an exception."""
    said: dict = {"asked": []}

    class Answering(payments.gateway_cls):
        capabilities = payments.gateway_cls.capabilities | {"refund_status"}

        def fetch_refund(self, refund_ref):
            said["asked"].append(refund_ref)
            answer = said.get(refund_ref, RefundStatus(RefundStatus.PENDING))
            if isinstance(answer, Exception):
                raise answer
            return answer

    monkeypatch.setitem(PaymentGateways.REGISTERED, Answering.key, Answering)
    return said


@pytest.fixture
def staff(db):
    from accounts.models import User

    return User.objects.create_user("boss@example.com", password="x-staff-pass-1", name="Boss", is_staff=True)


def paid(payments, credits=100):
    order = payments.buy("one_time", credits=credits)
    payments.send("succeeded", order)
    order.refresh_from_db()
    return order


def asked(order, amount, ref="refund_1", age_minutes=60, state="pending"):
    attempt = RefundAttempt.objects.create(
        token=uuid.uuid4(), order=order, amount_paise=amount, refund_ref=ref, state=state,
        created_at=timezone.now() - timedelta(minutes=age_minutes),
    )  # fmt: skip
    return attempt


class TestAskingTheProvider:
    def test_a_processed_refund_brings_the_credits_back_once_and_is_confirmed(self, payments, answers, user):
        order = paid(payments)
        attempt = asked(order, order.amount_paise)
        answers["refund_1"] = RefundStatus(RefundStatus.PROCESSED, order.amount_paise)

        report = RefundReconciler().run()

        order.refresh_from_db()
        attempt.refresh_from_db()
        assert (attempt.state, report.confirmed) == ("confirmed", 1) and attempt.resolved_at
        assert order.refunded_paise == order.amount_paise and Ledger().balance(user) == 0
        assert PaymentEventLog.objects.filter(event_id="refund:refund_1", outcome="applied").count() == 1

    def test_the_webhook_for_it_arriving_afterwards_changes_nothing_more(self, payments, answers, user):
        order = paid(payments)
        asked(order, 4000)
        answers["refund_1"] = RefundStatus(RefundStatus.PROCESSED, 4000)
        RefundReconciler().run()

        payments.send("refunded", order, amount=4000, event_id="refund:refund_1")

        order.refresh_from_db()
        assert order.refunded_paise == 4000 and Ledger().balance(user) == 60

    def test_a_failed_refund_is_marked_and_its_amount_is_free_to_ask_for_again(self, payments, answers, staff):
        order = paid(payments)
        attempt = asked(order, order.amount_paise)
        answers["refund_1"] = RefundStatus(RefundStatus.FAILED)

        report = RefundReconciler().run()

        attempt.refresh_from_db()
        assert (attempt.state, report.failed) == ("failed", 1) and attempt.resolved_at
        again = RefundDesk().refund(order.pk, staff, uuid.uuid4())
        assert (again.kind, again.amount_paise) == ("asked", order.amount_paise)

    def test_while_it_waits_the_amount_stays_spoken_for(self, payments, answers, staff):
        order = paid(payments)
        asked(order, order.amount_paise)

        outcome = RefundDesk().refund(order.pk, staff, uuid.uuid4())

        assert outcome.kind == "all_asked"

    def test_a_refund_still_pending_is_left_as_it_is(self, payments, answers):
        order = paid(payments)
        attempt = asked(order, 4000)

        report = RefundReconciler().run()

        attempt.refresh_from_db()
        assert attempt.state == "pending" and (report.asked, report.confirmed, report.failed) == (1, 0, 0)

    def test_one_asked_for_too_recently_is_not_asked_about(self, payments, answers):
        order = paid(payments)
        asked(order, 4000, age_minutes=2)

        report = RefundReconciler().run()

        assert answers["asked"] == [] and report.asked == 0

    def test_attempts_already_resolved_are_not_asked_about_again(self, payments, answers):
        order = paid(payments)
        asked(order, 4000, ref="r1", state="confirmed")
        asked(order, 4000, ref="r2", state="failed")

        RefundReconciler().run()

        assert answers["asked"] == []


class TestWhenTheProviderCannotAnswer:
    def test_a_gateway_that_cannot_answer_leaves_it_waiting_and_counts_it(self, payments):
        order = paid(payments)
        attempt = asked(order, 4000)  # the plain scripted gateway has no refund status

        report = RefundReconciler().run()

        attempt.refresh_from_db()
        assert attempt.state == "pending" and report.unanswerable == 1

    def test_a_provider_that_cannot_be_reached_leaves_it_waiting(self, payments, answers):
        order = paid(payments)
        attempt = asked(order, 4000)
        answers["refund_1"] = GatewayUnavailable("down")

        report = RefundReconciler().run()

        attempt.refresh_from_db()
        assert attempt.state == "pending" and report.unreachable == 1

    def test_a_gateway_that_says_it_cannot_when_asked_is_counted_as_unanswerable(self, payments, answers):
        order = paid(payments)
        asked(order, 4000)
        answers["refund_1"] = NotSupported("no")

        assert RefundReconciler().run().unanswerable == 1

    def test_a_gateway_switched_off_since_is_still_asked_about(self, payments, answers, settings):
        order = paid(payments)
        asked(order, order.amount_paise)
        answers["refund_1"] = RefundStatus(RefundStatus.PROCESSED, order.amount_paise)
        settings.PAYMENT_GATEWAYS_ENABLED = []

        assert RefundReconciler().run().confirmed == 1


class TestTheTask:
    def test_the_payments_task_runs_it_and_its_counts_are_unchanged(self, payments, answers):
        order = paid(payments)
        asked(order, 4000)
        answers["refund_1"] = RefundStatus(RefundStatus.FAILED)

        counts = reconcile()

        assert counts == {"asked": 0, "settled": 0, "retried": 0, "expired": 0}
        assert RefundAttempt.objects.get().state == "failed"


class TestMarkingFailedByHand:
    def test_an_attempt_whose_gateway_cannot_answer_is_marked_failed_and_logged(self, payments, staff):
        order = paid(payments)
        attempt = asked(order, order.amount_paise)

        RefundDesk().mark_failed(attempt.pk, staff)

        attempt.refresh_from_db()
        assert attempt.state == "failed" and attempt.resolved_at
        entry = AuditEntry.objects.get(action="payments.refund_failed")
        assert (entry.actor_email, entry.target_id) == ("boss@example.com", str(attempt.pk))
        assert (entry.before["state"], entry.after["state"]) == ("pending", "failed")
        assert RefundDesk().refund(order.pk, staff, uuid.uuid4()).kind == "asked"

    def test_an_attempt_a_provider_can_still_be_asked_about_is_refused(self, payments, answers, staff):
        order = paid(payments)
        attempt = asked(order, 4000)

        with pytest.raises(RefundNotMarkable, match="provider can still be asked"):
            RefundDesk().mark_failed(attempt.pk, staff)

        attempt.refresh_from_db()
        assert attempt.state == "pending" and not AuditEntry.objects.exists()

    @pytest.mark.parametrize("state", ["confirmed", "failed"])
    def test_an_attempt_that_is_not_waiting_is_refused(self, payments, staff, state):
        order = paid(payments)
        attempt = asked(order, 4000, state=state)

        with pytest.raises(RefundNotMarkable, match="not waiting"):
            RefundDesk().mark_failed(attempt.pk, staff)

        attempt.refresh_from_db()
        assert attempt.state == state

    def test_an_attempt_of_a_gateway_that_no_longer_exists_can_be_marked(self, payments, staff):
        order = paid(payments)
        attempt = asked(order, 4000)
        PaymentOrder.objects.filter(pk=order.pk).update(gateway="long_gone")

        RefundDesk().mark_failed(attempt.pk, staff)

        attempt.refresh_from_db()
        assert attempt.state == "failed"

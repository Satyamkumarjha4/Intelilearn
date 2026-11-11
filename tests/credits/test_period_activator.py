"""Unit under test: `credits.plans.activator.PeriodActivator`, which starts a plan period's credits when the period
starts
and marks periods that ended (credits plan T14, T19, §5.7).

Why: credits must never be granted before their period begins (three weeks bought today drip one week at a time) and
must be
spendable the instant it does, with no job to wait for. So the activator runs inside every movement of the wallet,
under the
wallet's lock, and the hourly job only sweeps the learners nobody has touched. It must be harmless to run twice, and
it must
not slow a wallet that has no plan.

Use cases:
- a queued period whose time has come gets a subscription bucket of its credits, expiring at its end, and becomes
  active; one
  whose time has not come gets nothing
- an active period whose end has come becomes ended; its credits are written off by the ledger's own expiry
- any movement of the wallet starts what is due first, so a hold or a debit can use the new credits
- reading the wallet or the plans through the API starts what is due, and a learner with no plan is not given a
  wallet by it
- it is harmless to ask again: nothing more is granted
- the sweep (what the hourly job calls) starts and ends periods for every learner with something due, counts them,
  and skips
  those with nothing
- a period's bucket is linked to the period, carries the purchase's id and the period's id on its ledger row
- `start_due` itself, given the books and the bucket maker the ledger passes it: it starts the queued period that is
  due, ends the one that is over, counts both on the books, grants a period once, and does nothing when asked again
"""

from datetime import timedelta

import pytest
from django.db import transaction

from credits.audit import LedgerAudit
from credits.ledger import Ledger, _Books
from credits.models import CreditBucket, CreditTransaction, PlanPeriod, Wallet
from credits.plans.activator import PeriodActivator
from credits.plans.desk import PurchaseDesk
from credits.plans.fulfilment import PlanFulfilment
from credits.plans.seed import PlanSeed

pytestmark = pytest.mark.django_db

DAY = timedelta(days=1)


@pytest.fixture(autouse=True)
def plans(db):
    PlanSeed().apply()


@pytest.fixture
def buy(ledger):
    def _buy(user, plan, **kwargs):
        return PlanFulfilment(ledger=ledger).fulfil(PurchaseDesk(ledger=ledger).open(user, plan, **kwargs))

    return _buy


def statuses(user):
    return [p.status for p in PlanPeriod.objects.filter(user=user).order_by("starts_at")]


class TestStartingAndEnding:
    def test_a_period_whose_time_has_come_gets_its_bucket_and_becomes_active(self, buy, ledger, user, clock):
        done = buy(user, "weekly_pro", quantity=2)
        first = done.periods[0]

        first.refresh_from_db()
        assert first.status == "active" and first.bucket is not None
        assert (first.bucket.source, first.bucket.amount_granted, first.bucket.expires_at) == (
            "subscription",
            100,
            first.ends_at,
        )

    def test_a_period_whose_time_has_not_come_gets_nothing(self, buy, user):
        buy(user, "weekly_pro", quantity=2)

        second = PlanPeriod.objects.get(user=user, position=2)

        assert second.status == "queued" and second.bucket is None

    def test_a_period_that_has_ended_is_marked_and_its_credits_are_written_off(self, buy, ledger, user, clock):
        buy(user, "weekly_pro", quantity=1)
        clock.advance(days=7)

        ledger.grant(user, "admin_grant", 1, "touch")

        assert statuses(user) == ["ended"]
        assert CreditTransaction.objects.filter(user=user, type="expire").count() == 1

    def test_the_ledger_row_of_a_period_names_it(self, buy, user):
        done = buy(user, "weekly_pro", quantity=1)
        period = done.periods[0]

        row = CreditTransaction.objects.get(user=user, type="grant")

        assert row.meta["source"] == "subscription" and row.meta["period"] == str(period.pk)
        assert row.idempotency_key == f"period:{period.pk}"


class TestStartDueItself:
    def test_it_starts_what_is_due_ends_what_is_over_counts_both_and_does_nothing_the_second_time(
        self, buy, ledger, user, clock
    ):
        buy(user, "weekly_pro", quantity=2)
        clock.advance(days=7)
        rows = CreditTransaction.objects.count()

        with transaction.atomic():
            books = _Books(user.pk, clock.now(), ledger.balance(user), None)
            PeriodActivator().start_due(books, Ledger._new_bucket)
            again = _Books(user.pk, clock.now(), books.balance, None)
            PeriodActivator().start_due(again, Ledger._new_bucket)

        assert (books.periods_started, books.periods_ended) == (1, 1)
        assert (again.periods_started, again.periods_ended) == (0, 0)
        assert statuses(user) == ["ended", "active"]
        second = PlanPeriod.objects.get(user=user, position=2)
        assert second.bucket is not None and second.bucket.amount_granted == 100
        assert CreditTransaction.objects.count() == rows + 1  # one grant, for the second period, under its own key
        assert CreditTransaction.objects.filter(idempotency_key=f"period:{second.pk}").count() == 1

    def test_it_leaves_alone_a_period_whose_time_has_not_come(self, buy, ledger, user, clock):
        buy(user, "weekly_pro", quantity=2)
        rows = CreditTransaction.objects.count()

        with transaction.atomic():
            books = _Books(user.pk, clock.now(), ledger.balance(user), None)
            PeriodActivator().start_due(books, Ledger._new_bucket)

        assert (books.periods_started, books.periods_ended) == (0, 0)
        assert statuses(user) == ["active", "queued"] and CreditTransaction.objects.count() == rows


class TestEveryMovementStartsWhatIsDue:
    def test_a_debit_can_use_the_new_weeks_credits(self, buy, ledger, user, clock):
        buy(user, "weekly_pro", quantity=2)
        ledger.debit(user, 100, "x", "all-of-week-one")
        clock.advance(days=7)

        ledger.debit(user, 40, "x", "from-week-two")

        assert ledger.balance(user) == 60

    def test_an_expiry_pass_does_it_too(self, buy, ledger, user, clock):
        buy(user, "weekly_pro", quantity=2)
        clock.advance(days=7)

        ledger.expire_due(user)

        assert statuses(user) == ["ended", "active"]

    def test_a_wallet_with_no_plan_is_not_slowed_by_a_query_per_period(
        self, ledger, user, give, django_assert_max_num_queries
    ):
        give(user, 5)

        with django_assert_max_num_queries(12):
            ledger.debit(user, 1, "x", "d")

    def test_a_learner_whose_wallet_is_busy_elsewhere_is_unaffected(self, buy, ledger, user, other_user, give, clock):
        buy(user, "weekly_pro", quantity=2)
        give(other_user, 7)
        clock.advance(days=7)

        ledger.debit(other_user, 1, "x", "d")

        assert statuses(user) == ["active", "queued"]  # theirs starts when their wallet is next touched


class TestReadingStartsWhatIsDue:
    def test_the_wallet_endpoint_shows_the_new_weeks_credits(self, signed_in_client, user):
        from django.utils import timezone

        from credits.ledger import Ledger

        real = Ledger()  # the views use the system clock, so this test buys on it too
        PlanFulfilment(ledger=real).fulfil(PurchaseDesk(ledger=real).open(user, "weekly_pro", quantity=2))
        hour = timedelta(hours=1)
        now = timezone.now()
        # week one ended an hour ago, week two began an hour ago
        first = PlanPeriod.objects.get(user=user, position=1)
        PlanPeriod.objects.filter(pk=first.pk).update(starts_at=now - 7 * DAY - hour, ends_at=now - hour)
        CreditBucket.objects.filter(pk=first.bucket_id).update(expires_at=now - hour)
        PlanPeriod.objects.filter(user=user, position=2).update(starts_at=now - hour, ends_at=now + 7 * DAY - hour)

        body = signed_in_client.get("/api/credits/wallet").json()

        assert body["balance"] == 100 and [b["source"] for b in body["buckets"]] == ["subscription"]
        assert statuses(user) == ["ended", "active"]

    def test_a_learner_with_no_plan_is_not_given_a_wallet_by_reading(self, signed_in_client, user):
        signed_in_client.get("/api/credits/wallet")
        signed_in_client.get("/api/credits/plans")

        assert not Wallet.objects.filter(user=user).exists()


class TestHarmless:
    def test_asking_again_grants_nothing_more(self, buy, ledger, user, clock):
        buy(user, "weekly_pro", quantity=2)
        clock.advance(days=7)
        ledger.grant(user, "admin_grant", 1, "touch-1")
        rows = CreditTransaction.objects.count()

        ledger.grant(user, "admin_grant", 1, "touch-2")

        assert CreditTransaction.objects.count() == rows + 1  # only the touch itself
        assert CreditBucket.objects.filter(user=user, source="subscription").count() == 2
        assert LedgerAudit().check(user).ok

    def test_has_due_says_whether_anything_is_waiting(self, buy, ledger, user, clock):
        buy(user, "weekly_pro", quantity=2)
        activator = PeriodActivator()

        assert activator.has_due(user.pk, clock.now()) is False
        assert activator.has_due(user.pk, clock.now() + 7 * DAY) is True


class TestTheSweep:
    def test_it_starts_and_ends_periods_for_learners_with_something_due_and_counts_them(
        self, buy, ledger, user, other_user, give, clock
    ):
        buy(user, "weekly_pro", quantity=2)
        buy(other_user, "monthly_pro")
        clock.advance(days=7)

        report = PeriodActivator().sweep(ledger)

        assert (report.learners, report.started, report.ended) == (1, 1, 1)
        assert statuses(user) == ["ended", "active"] and statuses(other_user) == ["active"]

    def test_a_second_sweep_does_nothing(self, buy, ledger, user, clock):
        buy(user, "weekly_pro", quantity=2)
        clock.advance(days=7)
        PeriodActivator().sweep(ledger)
        rows = CreditTransaction.objects.count()

        again = PeriodActivator().sweep(ledger)

        assert (again.learners, again.started, again.ended) == (0, 0, 0) and CreditTransaction.objects.count() == rows

    def test_it_keeps_going_after_one_learner_fails(self, buy, ledger, user, other_user, clock):
        buy(user, "weekly_pro", quantity=2)
        buy(other_user, "weekly_pro", quantity=2)
        clock.advance(days=7)

        class Flaky:
            clock = ledger.clock

            def activate_periods(self, learner):
                if learner == user.pk:
                    raise RuntimeError("down")
                return ledger.activate_periods(learner)

        report = PeriodActivator().sweep(Flaky())

        assert report.failures == (user.pk,) and report.learners == 1

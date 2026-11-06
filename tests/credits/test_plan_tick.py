"""Unit under test: the plan part of `credits.tick.HourlyTick` (credits plan T14, §5.9): starting the periods that
are due and
ending those that are over for learners nobody has touched.

Why: a wallet starts its own periods when it is touched, so nobody waits for the job to spend a new week's credits.
What is left
for the hourly job is the learner who has not come back: their credits should still be granted and written off on
time, so the
books and the history are right the next time anyone looks. It must be harmless to run twice and to run beside a
learner's own
requests.

Use cases:
- a tick starts a period that is due and ends one that is over, for a learner nobody touched, and reports how many
- a second tick changes nothing
- a learner who touched their wallet first has nothing left for the tick
- the tick reports a failing plan part by name and still runs the others
- the report the task returns keeps its shape (the plan counts are in the report object, not in the task's answer)
"""

from datetime import timedelta

import pytest

from credits.models import CreditTransaction, PlanPeriod
from credits.plans.desk import PurchaseDesk
from credits.plans.fulfilment import PlanFulfilment
from credits.plans.seed import PlanSeed
from credits.tick import HourlyTick

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


def test_a_tick_starts_what_is_due_and_ends_what_is_over_and_counts_them(buy, ledger, user, clock):
    buy(user, "weekly_pro", quantity=2)
    clock.advance(days=7)

    report = HourlyTick(ledger=ledger).run()

    assert (report.periods_started, report.periods_ended) == (1, 1)
    assert [p.status for p in PlanPeriod.objects.filter(user=user).order_by("starts_at")] == ["ended", "active"]
    assert ledger.balance(user) == 100


def test_a_second_tick_changes_nothing(buy, ledger, user, clock):
    buy(user, "weekly_pro", quantity=2)
    clock.advance(days=7)
    tick = HourlyTick(ledger=ledger)
    tick.run()
    rows = CreditTransaction.objects.count()

    second = tick.run()

    assert (second.periods_started, second.periods_ended) == (0, 0) and CreditTransaction.objects.count() == rows


def test_a_learner_who_touched_their_wallet_first_leaves_nothing_for_the_tick(buy, ledger, user, clock):
    buy(user, "weekly_pro", quantity=2)
    clock.advance(days=7)
    ledger.debit(user, 1, "x", "d")  # the learner's own movement starts the week

    report = HourlyTick(ledger=ledger).run()

    assert (report.periods_started, report.periods_ended) == (0, 0)


def test_a_failing_plan_part_is_named_and_the_others_still_run(buy, ledger, user, give, clock):
    class Broken:
        def sweep(self, ledger):
            raise RuntimeError("down")

    give(user, 5, days=1)
    clock.advance(days=2)

    report = HourlyTick(ledger=ledger, periods=Broken()).run()

    assert report.failed == ["periods"] and report.expired_buckets == 1


def test_the_tasks_answer_keeps_its_shape(user, give):
    from credits.tasks import tick

    give(user, 5)

    assert set(tick()) == {"expired_buckets", "expired_credits", "released_holds", "audit_breaks", "failed"}

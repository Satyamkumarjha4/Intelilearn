"""Unit under test: `credits.ledger.Ledger` with several real threads (and so several database connections) at once.

Why: the wallet row lock is the whole defence against double spending. A single-threaded test cannot tell a lock from no
lock, so these use real threads, real transactions (`transaction=True`) and a barrier that releases them together. They
check the outcomes that must hold in every interleaving, not one lucky order.

Use cases:
- many holds at once on a wallet that can cover only some of them: exactly as many succeed as the balance covers, the
  rest
  are refused for lack of credits, and nothing is spent twice
- two simultaneous holds that each need most of the balance: one wins and one is refused
- a hold racing the write-off of the bucket it would take from: whichever goes first, no lapsed credit is spent, nothing
  is spent twice, and the books balance
- two concurrent first movements for a learner who has no wallet both succeed and leave one wallet and a consistent
  running balance
- the same idempotency key sent by several threads at once writes one row and one bucket
- two different holds for one action and subject sent at once: one is made and the other is refused
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import connections
from django.db.models import Sum
from support.clock import FakeClock

from credits.audit import LedgerAudit
from credits.errors import InsufficientBalance
from credits.ledger import Ledger
from credits.models import CreditBucket, CreditHold, CreditTransaction, Wallet

pytestmark = pytest.mark.django_db(transaction=True)


def together(jobs):
    """Run each job in its own thread, released at the same moment; → what each returned or raised, in job order."""
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


def balanced(user) -> bool:
    ledger_sum = CreditTransaction.objects.filter(user=user).aggregate(total=Sum("amount"))["total"] or 0
    bucket_sum = CreditBucket.objects.filter(user=user).aggregate(total=Sum("amount_remaining"))["total"] or 0
    return ledger_sum == bucket_sum


def hold_job(ledger, user, amount):
    return lambda: ledger.place_hold(user, amount, "lesson.create", f"h-{uuid.uuid4()}", subject_id=uuid.uuid4())


def test_many_holds_at_once_never_spend_more_than_the_balance(user):
    ledger = Ledger(clock=FakeClock())
    ledger.grant(user, "signup", 10, "seed")

    results = together([hold_job(ledger, user, 3) for _ in range(8)])

    won = [r for r in results if not isinstance(r, Exception)]
    refused = [r for r in results if isinstance(r, InsufficientBalance)]
    assert len(won) == 3 and len(refused) == 5, results
    assert ledger.balance(user) == 1 and ledger.reserved(user) == 9
    assert CreditBucket.objects.get(user=user).amount_remaining == 1
    assert balanced(user) and LedgerAudit().check(user).ok


def test_two_holds_that_each_need_most_of_the_balance_let_one_win(user):
    ledger = Ledger(clock=FakeClock())
    ledger.grant(user, "signup", 10, "seed")

    results = together([hold_job(ledger, user, 6), hold_job(ledger, user, 6)])

    assert sorted(type(r).__name__ for r in results) == ["HoldMovement", "InsufficientBalance"]
    assert ledger.balance(user) == 4 and CreditHold.objects.count() == 1


def test_a_hold_racing_the_write_off_of_its_bucket_is_correct_whichever_goes_first(user):
    start = FakeClock()
    before = Ledger(clock=FakeClock(start.now()))  # the hold's view: the bucket still has a minute to live
    after = Ledger(clock=FakeClock(start.now() + timedelta(minutes=2)))  # the write-off's view: it has lapsed
    before.grant(user, "daily", 5, "dated", expires_at=start.now() + timedelta(minutes=1))
    before.grant(user, "signup", 5, "forever")

    results = together([hold_job(before, user, 5), lambda: after.expire_due(user)])

    hold, written_off = results
    assert not isinstance(hold, Exception) and not isinstance(written_off, Exception), results
    assert balanced(user) and LedgerAudit().check(user).ok
    dated = CreditBucket.objects.get(source="daily")
    forever = CreditBucket.objects.get(source="signup")
    # Either the hold took the dated credits first (and the write-off found them gone), or the write-off came first and
    # the hold took the other bucket. In both, the 5 credits held were never counted twice and no lapsed credit was
    # spent.
    assert dated.amount_remaining == 0
    assert dated.amount_remaining + forever.amount_remaining in (0, 5) and CreditHold.objects.get().amount == 5
    assert CreditTransaction.objects.filter(user=user, type="expire").count() in (0, 1)
    assert before.reserved(user) == 5


def test_two_first_movements_for_a_new_learner_both_succeed_with_one_wallet(user):
    ledger = Ledger(clock=FakeClock())
    assert not Wallet.objects.filter(user=user).exists()

    results = together([lambda n=n: ledger.grant(user, "daily", 5, f"first-{n}") for n in range(6)])

    assert all(not isinstance(r, Exception) for r in results), results
    assert Wallet.objects.filter(user=user).count() == 1
    assert CreditBucket.objects.filter(user=user).count() == 6
    after = list(CreditTransaction.objects.filter(user=user).order_by("id").values_list("balance_after", flat=True))
    assert after == [5, 10, 15, 20, 25, 30]  # each saw the one before it
    assert balanced(user)


def test_the_same_key_sent_at_once_writes_one_row(user):
    ledger = Ledger(clock=FakeClock())

    results = together([lambda: ledger.grant(user, "daily", 5, "one-key") for _ in range(6)])

    assert all(not isinstance(r, Exception) for r in results), results
    assert sum(1 for r in results if r.created) == 1
    assert CreditBucket.objects.filter(user=user).count() == 1 and CreditTransaction.objects.count() == 1


def test_two_different_holds_for_one_action_and_subject_let_one_be_made(user):
    ledger = Ledger(clock=FakeClock())
    ledger.grant(user, "signup", 20, "seed")
    subject = uuid.uuid4()

    def job(key):
        return lambda: ledger.place_hold(user, 2, "lesson.create", key, subject_id=subject)

    results = together([job("a"), job("b")])

    assert sorted(type(r).__name__ for r in results) == ["HoldConflict", "HoldMovement"], results
    assert CreditHold.objects.filter(subject_id=subject).count() == 1 and ledger.balance(user) == 18

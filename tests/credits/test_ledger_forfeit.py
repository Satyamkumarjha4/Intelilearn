"""Unit under test: `Ledger.forfeit` (writing off a learner's remaining credits, for a closed account) and
`Ledger.exclusive` (holding a learner's wallet lock across several steps).

Why: closing an account must not leave credits that nobody can spend, and must not break the one equation of the ledger.
The write-off is a row like any other: the credits come out of the buckets and out of the balance by the same amount,
so the
books still balance, and the row says what was forfeited. `exclusive` is what lets a service check a rule and then spend
without another request slipping in between.

Use cases:
- forfeit empties every bucket and writes one row for the whole balance; the ledger still equals the buckets; the
  balance is 0
- buckets that never expire, buckets that will, and a bucket that has lapsed (written off first, as expiry) are all
  emptied
- it is repeatable on its key, and a learner with nothing records a row of 0 so the closing is on the record
- credits reserved in a hold are not part of the balance and are untouched (the caller releases holds first)
- the reason is kept on the row
- exclusive makes the wallet if it is new and locks it; steps inside see each other's writes; it nests with ledger calls
"""

import pytest

from credits.audit import LedgerAudit
from credits.models import CreditBucket, CreditTransaction, Wallet

pytestmark = pytest.mark.django_db


def test_it_empties_every_bucket_with_one_row_for_the_whole_balance(ledger, user, give):
    give(user, 30, source="signup")
    give(user, 5, days=40)
    give(user, 8, source="purchase", days=300)

    done = ledger.forfeit(user, "forfeit-1", reason="Account closed")

    row = done.transaction
    assert (row.type, row.amount, row.balance_after) == ("forfeit", -43, 0)
    assert row.meta["reason"] == "Account closed" and row.bucket_allocations
    assert ledger.balance(user) == 0
    assert not CreditBucket.objects.filter(user=user, amount_remaining__gt=0).exists()
    assert LedgerAudit().check(user).ok


def test_a_lapsed_bucket_is_written_off_as_expiry_first(ledger, user, give, clock):
    give(user, 5, days=1)
    give(user, 7, source="signup")
    clock.advance(days=2)

    done = ledger.forfeit(user, "forfeit-1", reason="Account closed")

    assert done.transaction.amount == -7
    assert [r.type for r in CreditTransaction.objects.filter(user=user).order_by("id")] == [
        "grant",
        "grant",
        "expire",
        "forfeit",
    ]
    assert LedgerAudit().check(user).ok


def test_it_is_repeatable_on_its_key(ledger, user, give):
    give(user, 5)
    first = ledger.forfeit(user, "forfeit-1", reason="Account closed")
    give(user, 3)  # (it should never happen after closing; the key still protects)

    again = ledger.forfeit(user, "forfeit-1", reason="Account closed")

    assert not again.created and again.transaction.pk == first.transaction.pk and ledger.balance(user) == 3


def test_a_learner_with_nothing_still_has_the_closing_on_the_record(ledger, user):
    done = ledger.forfeit(user, "forfeit-1", reason="Account closed")

    assert (done.transaction.type, done.transaction.amount, done.transaction.balance_after) == ("forfeit", 0, 0)


def test_reserved_credits_are_not_part_of_the_balance_and_are_untouched(ledger, user, give):
    import uuid

    give(user, 10)
    hold = ledger.place_hold(user, 4, "lesson.create", "h", subject_id=uuid.uuid4()).hold

    done = ledger.forfeit(user, "forfeit-1", reason="Account closed")

    assert done.transaction.amount == -6
    hold.refresh_from_db()
    assert hold.status == "held" and LedgerAudit().check(user).ok


def test_another_learners_credits_are_not_touched(ledger, user, other_user, give):
    give(user, 5)
    give(other_user, 9)

    ledger.forfeit(user, "forfeit-1", reason="Account closed")

    assert ledger.balance(other_user) == 9


class TestExclusive:
    def test_it_makes_the_wallet_if_it_is_new_and_locks_it(self, ledger, user):
        assert not Wallet.objects.filter(user=user).exists()

        with ledger.exclusive(user):
            assert Wallet.objects.filter(user=user).exists()

    def test_steps_inside_see_each_others_writes_and_nest_with_ledger_calls(self, ledger, user, give):
        give(user, 5)

        with ledger.exclusive(user):
            before = ledger.balance(user)
            ledger.debit(user, 2, "x", "d1")
            after = ledger.balance(user)

        assert (before, after) == (5, 3)

    def test_an_error_inside_rolls_everything_back(self, ledger, user, give):
        give(user, 5)

        with pytest.raises(RuntimeError), ledger.exclusive(user):
            ledger.debit(user, 2, "x", "d1")
            raise RuntimeError("boom")

        assert ledger.balance(user) == 5

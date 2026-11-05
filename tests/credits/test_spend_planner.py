"""Unit under test: `credits.planner.SpendPlanner` (and `SpendBucket`, `BucketAllocation`, `SpendPlan`), the pure
rule for
which buckets pay for a spend.

Why: this is the rule that decides which of a learner's credits go first. Earliest expiry first means the credits that
are about to lapse are never wasted while long-lived ones sit untouched, and a bucket that has lapsed, run dry or been
revoked must never be spent from. It has no database so that every row of the rule can be a line in a table.

Use cases:
- the bucket that expires soonest is spent first; a bucket that never expires goes last; equal expiry goes to the older
  bucket, then to the lower id
- a spend spans several buckets in that order, takes the exact amount from the last one it needs, and leaves the rest
- an exact fit takes the whole bucket; one credit short reports the shortfall and the allocations that were possible;
  an empty list is all shortfall
- a spend of zero allocates nothing and is never short; a negative spend is a programming error
- a bucket that expired (at or before the instant), is empty or is revoked is skipped, and a bucket that expires a
  moment after the instant is still spendable
- the plan never allocates more than a bucket holds, and its allocations add up to the spend minus the shortfall
"""

from datetime import UTC, datetime, timedelta

import pytest

from credits.planner import BucketAllocation, SpendBucket, SpendPlan, SpendPlanner

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def bucket(id, remaining, expires=None, *, age_days=0, revoked=False) -> SpendBucket:
    """A bucket; `expires` is days from NOW (None never), `age_days` how long ago it was made."""
    return SpendBucket(
        id=id,
        remaining=remaining,
        expires_at=None if expires is None else NOW + expires * DAY,
        created_at=NOW - age_days * DAY,
        revoked=revoked,
    )


def plan(buckets, amount, now=NOW) -> SpendPlan:
    return SpendPlanner().plan(buckets, amount, now)


def taken(result: SpendPlan) -> list[tuple]:
    return [(a.bucket_id, a.amount) for a in result.allocations]


class TestOrder:
    def test_the_bucket_that_expires_soonest_is_spent_first(self):
        result = plan([bucket("late", 5, 30), bucket("soon", 5, 2), bucket("mid", 5, 10)], 3)

        assert taken(result) == [("soon", 3)]

    def test_a_bucket_that_never_expires_goes_last(self):
        result = plan([bucket("never", 5, None), bucket("dated", 5, 300)], 7)

        assert taken(result) == [("dated", 5), ("never", 2)]

    def test_equal_expiry_goes_to_the_older_bucket(self):
        result = plan([bucket("new", 5, 10, age_days=1), bucket("old", 5, 10, age_days=9)], 2)

        assert taken(result) == [("old", 2)]

    def test_equal_expiry_and_age_goes_to_the_lower_id(self):
        result = plan([bucket("b", 5, 10), bucket("a", 5, 10)], 2)

        assert taken(result) == [("a", 2)]

    def test_two_buckets_that_never_expire_are_ordered_by_age_then_id(self):
        result = plan([bucket("x", 4, None, age_days=1), bucket("y", 4, None, age_days=5)], 6)

        assert taken(result) == [("y", 4), ("x", 2)]

    def test_the_input_order_does_not_matter(self):
        buckets = [bucket("a", 3, 1), bucket("b", 3, 2), bucket("c", 3, None)]

        assert taken(plan(buckets, 8)) == taken(plan(list(reversed(buckets)), 8)) == [("a", 3), ("b", 3), ("c", 2)]


class TestAmounts:
    def test_a_spend_spans_buckets_and_takes_only_what_the_last_one_needs(self):
        result = plan([bucket("a", 4, 1), bucket("b", 4, 2), bucket("c", 4, 3)], 9)

        assert taken(result) == [("a", 4), ("b", 4), ("c", 1)]
        assert result.shortfall == 0 and result.ok and result.total == 9

    def test_an_exact_fit_takes_the_whole_bucket(self):
        result = plan([bucket("a", 5, 1)], 5)

        assert taken(result) == [("a", 5)] and result.ok

    def test_one_short_reports_the_shortfall_and_what_was_possible(self):
        result = plan([bucket("a", 2, 1), bucket("b", 3, 2)], 6)

        assert taken(result) == [("a", 2), ("b", 3)]
        assert result.shortfall == 1 and not result.ok and result.total == 5

    def test_no_buckets_is_all_shortfall(self):
        result = plan([], 4)

        assert result.allocations == () and result.shortfall == 4 and not result.ok

    def test_a_spend_of_zero_allocates_nothing_and_is_never_short(self):
        for buckets in ([], [bucket("a", 5, 1)]):
            result = plan(buckets, 0)
            assert result.allocations == () and result.shortfall == 0 and result.ok

    def test_a_negative_spend_is_a_programming_error(self):
        with pytest.raises(ValueError):
            plan([bucket("a", 5)], -1)


class TestWhatIsSkipped:
    def test_a_bucket_that_expired_is_skipped(self):
        result = plan([bucket("lapsed", 5, -1), bucket("live", 5, 10)], 3)

        assert taken(result) == [("live", 3)]

    def test_a_bucket_that_expires_at_the_instant_is_skipped_and_one_a_moment_later_is_not(self):
        at_now = SpendBucket("at", 5, NOW, NOW - DAY, False)
        later = SpendBucket("later", 5, NOW + timedelta(seconds=1), NOW - DAY, False)

        assert taken(plan([at_now, later], 5)) == [("later", 5)]

    def test_an_empty_bucket_is_skipped(self):
        assert taken(plan([bucket("empty", 0, 1), bucket("live", 5, 2)], 2)) == [("live", 2)]

    def test_a_revoked_bucket_is_skipped_however_much_it_holds(self):
        result = plan([bucket("revoked", 50, 1, revoked=True), bucket("live", 5, 2)], 8)

        assert taken(result) == [("live", 5)] and result.shortfall == 3

    def test_nothing_spendable_at_all_is_all_shortfall(self):
        result = plan([bucket("a", 5, -2), bucket("b", 0), bucket("c", 9, revoked=True)], 1)

        assert result.allocations == () and result.shortfall == 1

    def test_the_instant_decides_what_has_lapsed(self):
        buckets = [bucket("a", 5, 2), bucket("b", 5, 9)]

        assert taken(plan(buckets, 5, now=NOW)) == [("a", 5)]
        assert taken(plan(buckets, 5, now=NOW + 3 * DAY)) == [("b", 5)]


class TestTheValues:
    def test_a_plan_never_takes_more_than_a_bucket_holds_and_adds_up(self):
        buckets = [bucket("a", 3, 1), bucket("b", 2, 2), bucket("c", 7, None)]
        held = {b.id: b.remaining for b in buckets}

        for amount in range(0, 16):
            result = plan(buckets, amount)
            assert all(0 < a.amount <= held[a.bucket_id] for a in result.allocations)
            assert result.total + result.shortfall == amount

    def test_the_values_are_frozen(self):
        allocation = BucketAllocation("a", 2)

        with pytest.raises(AttributeError):
            allocation.amount = 3  # type: ignore[misc]
        with pytest.raises(AttributeError):
            bucket("a", 1).remaining = 2  # type: ignore[misc]

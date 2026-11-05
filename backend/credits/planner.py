"""Which buckets pay for a spend: the pure rule of the ledger (credits plan T6).

Earliest expiry first, a bucket that never expires last, then the older bucket, then the lower id. A bucket that has
lapsed, is empty or was revoked is never spent from. The planner knows nothing about the database, so every row of the
rule is a line in a table test; `Ledger` turns the buckets it has locked into `SpendBucket`s and applies the plan.
"""

from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SpendBucket:
    """What the planner needs to know of a bucket."""

    id: Hashable
    remaining: int
    expires_at: datetime | None  # None: never
    created_at: datetime
    revoked: bool = False


@dataclass(frozen=True)
class BucketAllocation:
    bucket_id: Any
    amount: int


@dataclass(frozen=True)
class SpendPlan:
    """The buckets to take from, in order, and how many credits no bucket could cover."""

    allocations: tuple[BucketAllocation, ...]
    shortfall: int

    @property
    def ok(self) -> bool:
        return self.shortfall == 0

    @property
    def total(self) -> int:
        """What the allocations take."""
        return sum(a.amount for a in self.allocations)


class SpendPlanner:
    def plan(self, buckets: Iterable[SpendBucket], amount: int, now: datetime) -> SpendPlan:
        if amount < 0:
            raise ValueError("A spend cannot be negative.")
        allocations: list[BucketAllocation] = []
        needed = amount
        for bucket in self.in_order(buckets, now):
            if needed == 0:
                break
            take = min(needed, bucket.remaining)
            allocations.append(BucketAllocation(bucket.id, take))
            needed -= take
        return SpendPlan(tuple(allocations), needed)

    def in_order(self, buckets: Iterable[SpendBucket], now: datetime) -> list[SpendBucket]:
        """The buckets that can be spent from now, in the order they will be."""
        return sorted(self._spendable(buckets, now), key=self._order)

    @staticmethod
    def _spendable(buckets: Iterable[SpendBucket], now: datetime) -> list[SpendBucket]:
        return [
            b for b in buckets if b.remaining > 0 and not b.revoked and (b.expires_at is None or b.expires_at > now)
        ]

    @staticmethod
    def _order(bucket: SpendBucket) -> tuple:
        # A bucket that never expires sorts after every dated one; its date is a placeholder that is never compared.
        return (bucket.expires_at is None, bucket.expires_at or bucket.created_at, bucket.created_at, str(bucket.id))

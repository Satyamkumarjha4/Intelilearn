"""Fixtures for the credits tests: a stopped `clock`, a `ledger` that reads it, and `give` to put credits in a
wallet."""

import itertools

import pytest
from support.clock import FakeClock

from credits.ledger import Ledger


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def ledger(clock):
    return Ledger(clock=clock)


@pytest.fixture
def give(ledger, clock):
    """give(user, 10, source="daily", days=5, key=None, purchase_id=None): grant a bucket that expires `days` from
    now."""
    counter = itertools.count(1)

    def _give(user, amount, source="daily", days=None, key=None, purchase_id=None):
        expires = None if days is None else clock.now() + __import__("datetime").timedelta(days=days)
        return ledger.grant(
            user, source, amount, key or f"test-grant-{user.pk}-{next(counter)}", expires_at=expires,
            purchase_id=purchase_id,
        )  # fmt: skip

    return _give

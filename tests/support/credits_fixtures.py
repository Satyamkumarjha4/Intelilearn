"""Fixtures for tests that run with the credit gate on (registered for every test through tests/conftest.py).

- `credits_on`: switches `ACTION_GATE` to `CreditGate`, makes sure the price table has the plan's prices (a test that
  flushes the database, `transaction=True`, takes the migration's seed with it), and gives back a `CreditsOn` to put
  credits in a learner's wallet and read what was reserved.
- `earning_on`: `credits_on` plus `CreditsActivitySink`, so the daily credit and the streak are earned too.
- `_pin_the_open_gate` (autouse): every test starts on `OpenGate` and the do-nothing activity sink whatever the defaults
  are (they became the credit gate and the credits sink in phase 10.9), so no test written before that changes meaning.
  A test that wants another gate sets `ACTION_GATE` itself.

The models are imported inside the fixtures, because this module is loaded before Django is set up.
"""

import itertools
from datetime import timedelta

import pytest


class CreditsOn:
    """What a test does with credits: put some in a wallet, and look at the reserved and the spendable."""

    def __init__(self):
        from credits.ledger import Ledger

        self.ledger = Ledger()
        self.counter = itertools.count(1)

    def fund(self, user, credits: int, *, days: int | None = None, source: str = "signup"):
        """Give `user` a bucket of `credits` (expiring in `days`, or never)."""
        expires = None if days is None else self.ledger.clock.now() + timedelta(days=days)
        return self.ledger.grant(user, source, credits, f"fund-{user.pk}-{next(self.counter)}", expires_at=expires)

    def balance(self, user) -> int:
        return self.ledger.balance(user)

    def reserved(self, user) -> int:
        return self.ledger.reserved(user)

    def holds(self, user=None):
        from django.db.models import Min

        from credits.models import CreditHold

        found = CreditHold.objects.annotate(first=Min("transactions__id")).order_by("first")
        return list(found.filter(user=user) if user is not None else found)

    def live_holds(self, user=None):
        return [h for h in self.holds(user) if h.status == "held"]


@pytest.fixture(autouse=True)
def _pin_the_open_gate():
    """Not via the `settings` fixture: a test may take a parameter of that name (one does), which would shadow it. The
    do-nothing sink is pinned with the open gate: since phase 10.9 the defaults earn and charge, and a test that wants
    either asks for it (`credits_on`, `earning_on`)."""
    from django.test import override_settings

    with override_settings(ACTION_GATE="lessons.metering.OpenGate", ACTIVITY_SINK="lessons.activity.NullActivity"):
        yield


@pytest.fixture
def earning_on(credits_on, settings):
    """The credit gate and earning together, as production will have them: studying earns the daily credit and the
    streak.
    Separate from `credits_on` so the tests that count credits exactly are not changed by the day's credit."""
    settings.ACTIVITY_SINK = "credits.activity.CreditsActivitySink"
    return credits_on


@pytest.fixture
def credits_on(settings, db):
    from credits.pricing.seed import PriceSeed

    PriceSeed().apply()
    settings.ACTION_GATE = "credits.gate.CreditGate"
    return CreditsOn()

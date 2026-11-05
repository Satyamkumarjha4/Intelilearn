"""Unit under test: the invariant of the ledger (credits plan T4) under a long, random, but repeatable run of movements.

Why: "the sum of a learner's ledger rows equals the sum of their buckets" is the one equation that tells us no credit
was
made or lost by a bug. Unit tests check each movement alone; this checks that no order of movements breaks it, and that
the running balance on every row is honest, the buckets stay within their grant, and nothing is ever negative.

Use cases:
- after hundreds of seeded random grants, holds, commits, releases, debits, adjustments, claw-backs, expiries and passes
  of time (with refused movements and repeated keys mixed in), the sum of the rows equals the sum of the buckets, all
  the
  way through and at the end, for each of several seeds and two learners that share one clock
- every row's `balance_after` equals the sum of the amounts up to and including it
- no bucket is ever below zero or above what it was granted, the balance a learner can spend is never more than the
  books hold, and the audit finds no break
- every credit that left through a hold is still held, spent, or back (a release returns or forfeits exactly what its
  hold took), and the reserved amount is the sum of the holds that are held
- a hold that was committed cannot then be released, and one that was released cannot be committed
"""

import random
import uuid
from datetime import timedelta

import pytest
from django.db.models import Sum

from credits.audit import LedgerAudit
from credits.errors import HoldNotHeld, InsufficientBalance
from credits.models import CreditBucket, CreditHold, CreditTransaction

pytestmark = pytest.mark.django_db

SEEDS = [1, 7, 42, 2026, 31337]
STEPS = 300
SOURCES = ["signup", "daily", "weekly_streak", "monthly_streak", "purchase", "subscription"]


class Run:
    """One random walk over a ledger: it picks a movement, tries it, and shrugs at the refusals a real caller would
    get."""

    def __init__(self, ledger, clock, users, seed):
        self.ledger, self.clock, self.users, self.random = ledger, clock, users, random.Random(seed)
        self.keys = 0
        self.purchases = {u.pk: [] for u in users}

    def key(self, label):
        self.keys += 1
        return f"{label}-{self.keys}"

    def step(self):
        user = self.random.choice(self.users)
        action = self.random.choices(
            ["grant", "hold", "commit", "release", "debit", "adjust", "claw", "wait", "expire", "repeat"],
            weights=[18, 22, 10, 12, 8, 4, 4, 10, 6, 6],
        )[0]
        getattr(self, action)(user)

    def grant(self, user):
        source = self.random.choice(SOURCES)
        days = self.random.choice([None, 1, 3, 10, 40])
        purchase = None
        if source == "purchase":
            purchase = uuid.uuid4()
            self.purchases[user.pk].append(purchase)
        expires = None if days is None else self.clock.now() + timedelta(days=days, hours=self.random.randint(0, 5))
        self.ledger.grant(
            user, source, self.random.randint(1, 20), self.key("grant"), expires_at=expires, purchase_id=purchase
        )

    def hold(self, user):
        try:
            self.ledger.place_hold(
                user, self.random.randint(0, 12), "lesson.create", self.key("hold"), subject_id=uuid.uuid4()
            )
        except InsufficientBalance:
            pass

    def held(self, user):
        return list(CreditHold.objects.filter(user=user, status="held").values_list("pk", flat=True))

    def commit(self, user):
        if holds := self.held(user):
            self.ledger.commit(self.random.choice(holds))

    def release(self, user):
        if holds := self.held(user):
            self.ledger.release(self.random.choice(holds))

    def debit(self, user):
        try:
            self.ledger.debit(user, self.random.randint(1, 8), "streak_repair", self.key("debit"), type="repair")
        except InsufficientBalance:
            pass

    def adjust(self, user):
        try:
            amount = self.random.choice([-1, 1]) * self.random.randint(1, 15)
            self.ledger.adjust(user, amount, self.key("adj"), reason="test", actor="staff")
        except InsufficientBalance:
            pass

    def claw(self, user):
        if self.purchases[user.pk]:
            self.ledger.claw_back(
                user, self.random.choice(self.purchases[user.pk]), self.random.randint(1, 30), self.key("claw")
            )

    def wait(self, user):
        self.clock.advance(hours=self.random.randint(1, 60))

    def expire(self, user):
        self.ledger.expire_due(user)

    def repeat(self, user):
        """Send the last movement's key again: it must change nothing."""
        last = CreditTransaction.objects.filter(user=user).order_by("-id").first()
        before = CreditTransaction.objects.count()
        if last is not None and last.type == "grant":
            self.ledger.grant(user, "daily", 1, last.idempotency_key)
        elif last is not None and last.type == "commit":
            self.ledger.commit(last.hold_id, last.idempotency_key)
        elif last is not None and last.type == "release":
            self.ledger.release(last.hold_id, last.idempotency_key)
        assert CreditTransaction.objects.count() == before


@pytest.fixture
def walkers(ledger, clock, user, other_user):
    return lambda seed: Run(ledger, clock, [user, other_user], seed)


def sums(user):
    ledger_sum = CreditTransaction.objects.filter(user=user).aggregate(total=Sum("amount"))["total"] or 0
    bucket_sum = CreditBucket.objects.filter(user=user).aggregate(total=Sum("amount_remaining"))["total"] or 0
    return ledger_sum, bucket_sum


@pytest.mark.parametrize("seed", SEEDS)
def test_the_books_balance_all_the_way_through_a_random_run(walkers, ledger, user, other_user, seed):
    run = walkers(seed)
    learners = (user, other_user)

    for n in range(STEPS):
        run.step()
        if n % 50 == 49:  # the equation holds all the way through, not only at the end
            for learner in learners:
                assert sums(learner)[0] == sums(learner)[1], f"seed {seed}, step {n}"

    assert CreditTransaction.objects.count() > STEPS // 3  # the run did real work
    for learner in learners:
        ledger_sum, bucket_sum = sums(learner)
        assert ledger_sum == bucket_sum
        assert 0 <= ledger.balance(learner) <= bucket_sum
        check_rows(learner)
        check_holds(ledger, learner)
    for bucket in CreditBucket.objects.all():
        assert 0 <= bucket.amount_remaining <= bucket.amount_granted
    assert LedgerAudit().check_all().breaks == ()


def check_rows(learner):
    """Every row's `balance_after` is the sum of the amounts up to and including it."""
    running = 0
    for row in CreditTransaction.objects.filter(user=learner).order_by("id"):
        running += row.amount
        assert row.balance_after == running, f"row {row.pk} ({row.type})"


def check_holds(ledger, learner):
    """What left through holds is held, spent or back: a release returns or forfeits exactly what its hold took."""
    holds = CreditHold.objects.filter(user=learner)
    releases = CreditTransaction.objects.filter(user=learner, type="release")
    returned = releases.aggregate(total=Sum("amount"))["total"] or 0
    forfeited = sum(row.meta["forfeited"] for row in releases)
    assert returned + forfeited == (holds.filter(status="released").aggregate(total=Sum("amount"))["total"] or 0)
    assert ledger.reserved(learner) == (holds.filter(status="held").aggregate(total=Sum("amount"))["total"] or 0)


def test_a_hold_settled_twice_the_other_way_is_always_refused(walkers, ledger, user):
    run = walkers(5)
    for _ in range(80):
        run.step()

    for hold in CreditHold.objects.filter(user=user).exclude(status="held"):
        with pytest.raises(HoldNotHeld):
            (ledger.release if hold.status == "committed" else ledger.commit)(hold.pk, key=f"again-{hold.pk}")

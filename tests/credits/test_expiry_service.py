"""Unit under test: `credits.expiry.ExpiryService`, the pass that writes off every learner's lapsed buckets (the work of
the hourly `credits.tick`, which phase 10.3 schedules).

Why: a lapsed bucket is already unspendable, because every movement and the balance leave it out. What the pass adds is
that the books say so (an `expire` row) for learners who have not moved lately, which keeps the history and the audit
honest. It must find only what has lapsed, touch each bucket once, and be harmless to run twice or from two places.

Use cases:
- it writes one expire row for each lapsed bucket that still holds credits, across every learner, and reports how many
  learners, buckets and credits that was
- it leaves buckets that have not lapsed, buckets that never expire and empty buckets alone
- a second pass, or a pass after a learner's own movement already wrote the bucket off, finds nothing
- it keeps going after one learner's wallet fails, and reports the failure
"""

import pytest

from credits.expiry import ExpiryService
from credits.models import CreditBucket, CreditTransaction

pytestmark = pytest.mark.django_db


@pytest.fixture
def service(ledger):
    return ExpiryService(ledger)


def test_it_writes_off_every_lapsed_bucket_across_learners_and_reports_the_totals(
    service, give, clock, user, other_user
):
    give(user, 5, days=1)
    give(user, 3, days=2)
    give(other_user, 7, days=1)
    give(user, 9, days=30)
    clock.advance(days=3)

    report = service.run()

    assert (report.learners, report.buckets, report.credits) == (2, 3, 15)
    assert CreditTransaction.objects.filter(type="expire").count() == 3
    assert not CreditBucket.objects.filter(expires_at__lte=clock.now(), amount_remaining__gt=0).exists()


def test_it_leaves_alone_what_has_not_lapsed_never_expires_or_is_empty(service, give, ledger, clock, user):
    give(user, 5, days=10)
    give(user, 5, source="signup")
    give(user, 4, days=1)
    ledger.debit(user, 4, "x", "d")  # the dated one is spent first, so it is empty
    clock.advance(days=2)

    report = service.run()

    assert (report.learners, report.buckets, report.credits) == (0, 0, 0)
    assert CreditTransaction.objects.filter(type="expire").count() == 0


def test_a_second_pass_finds_nothing(service, give, clock, user):
    give(user, 5, days=1)
    clock.advance(days=2)
    service.run()

    again = service.run()

    assert (again.buckets, again.credits) == (0, 0) and CreditTransaction.objects.filter(type="expire").count() == 1


def test_a_bucket_the_learners_own_movement_wrote_off_is_not_written_twice(service, give, ledger, clock, user):
    give(user, 5, days=1)
    give(user, 5, source="signup")
    clock.advance(days=2)
    ledger.debit(user, 1, "x", "d")  # writes the lapsed bucket off first

    report = service.run()

    assert report.buckets == 0 and CreditTransaction.objects.filter(type="expire").count() == 1


def test_it_keeps_going_after_one_wallet_fails_and_says_which(give, ledger, clock, user, other_user):
    give(user, 5, days=1)
    give(other_user, 6, days=1)
    clock.advance(days=2)

    class Flaky:
        """The real ledger, except that one learner's write-off raises."""

        def __init__(self, real, bad):
            self.real, self.bad, self.clock = real, bad, real.clock

        def expire_due(self, learner):
            if learner == self.bad:
                raise RuntimeError("database went away")
            return self.real.expire_due(learner)

    report = ExpiryService(Flaky(ledger, user.pk)).run()

    assert (report.learners, report.credits) == (1, 6)
    assert list(report.failures) == [user.pk]
    assert CreditBucket.objects.get(user=user).amount_remaining == 5


def test_the_clock_decides_what_has_lapsed(service, give, clock, user):
    give(user, 5, days=1)
    clock.advance(days=1, seconds=-1)
    assert service.run().buckets == 0

    clock.advance(seconds=1)

    assert service.run().buckets == 1

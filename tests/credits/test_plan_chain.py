"""Unit under test: `credits.plans.chain.PlanChain` (credits plan T19, spec §5.2 and §5.3), the pure rule for when a
purchase's periods run.

Why: a learner may buy several weeks at once, or another plan while one is running. The rules are the spec's: one
plan active
at a time, a new purchase starts when the last period ends, several weeks are consecutive periods and never granted
all at
once, and there is a limit to how far ahead anyone can queue. Times are exact instants, so the boundaries are table
cases.

Use cases:
- with nothing running a purchase starts now, and its periods follow one another with no gap and no overlap
- three weeks are three consecutive 7-day periods, numbered from 1, each carrying its own credits
- a purchase made while a period is running starts when the last period ends, whatever plan it belongs to
- a last period that ended already, or ends this very instant, is no reason to wait
- 28-day plans last 28 days
- the number of periods open (running or waiting) after the purchase may not exceed the limit; exactly at the limit
  is fine
- a quantity below 1, or a period of no length, is a programming error
"""

from datetime import UTC, datetime, timedelta

import pytest

from credits.plans.chain import PlanChain
from credits.plans.errors import QueueFull

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def chain(**kwargs):
    defaults = {"last_end": None, "now": NOW, "period_days": 7, "credits": 100, "quantity": 1}
    return PlanChain().periods(**{**defaults, **kwargs})


def starts(spans):
    return [span.starts_at for span in spans]


def test_with_nothing_running_it_starts_now():
    (span,) = chain()

    assert (span.position, span.starts_at, span.ends_at, span.credits) == (1, NOW, NOW + 7 * DAY, 100)


def test_three_weeks_are_three_consecutive_periods_each_with_its_own_credits():
    spans = chain(quantity=3)

    assert [s.position for s in spans] == [1, 2, 3]
    assert starts(spans) == [NOW, NOW + 7 * DAY, NOW + 14 * DAY]
    assert [s.ends_at for s in spans] == [NOW + 7 * DAY, NOW + 14 * DAY, NOW + 21 * DAY]
    assert [s.credits for s in spans] == [100, 100, 100]
    assert all(a.ends_at == b.starts_at for a, b in zip(spans, spans[1:], strict=False))  # no gap, no overlap


def test_a_purchase_made_during_a_period_starts_when_it_ends():
    running_until = NOW + 3 * DAY

    (span,) = chain(last_end=running_until, period_days=28, credits=500)

    assert (span.starts_at, span.ends_at, span.credits) == (running_until, running_until + 28 * DAY, 500)


def test_several_weeks_queue_behind_the_last_period():
    spans = chain(last_end=NOW + 2 * DAY, quantity=2)

    assert starts(spans) == [NOW + 2 * DAY, NOW + 9 * DAY]


@pytest.mark.parametrize("ended", [NOW, NOW - timedelta(seconds=1), NOW - 30 * DAY])
def test_a_last_period_that_has_ended_is_no_reason_to_wait(ended):
    (span,) = chain(last_end=ended)

    assert span.starts_at == NOW


def test_a_last_period_ending_a_moment_from_now_is_waited_for():
    (span,) = chain(last_end=NOW + timedelta(seconds=1))

    assert span.starts_at == NOW + timedelta(seconds=1)


@pytest.mark.parametrize(("days", "credits"), [(28, 500), (28, 750)])
def test_the_monthly_plans_last_28_days(days, credits):
    (span,) = chain(period_days=days, credits=credits)

    assert span.ends_at - span.starts_at == timedelta(days=28) and span.credits == credits


class TestTheLimit:
    def test_exactly_at_the_limit_is_fine(self):
        spans = chain(quantity=3, open_periods=9, limit=12)

        assert len(spans) == 3

    def test_one_over_is_refused(self):
        with pytest.raises(QueueFull) as refused:
            chain(quantity=3, open_periods=10, limit=12)

        assert refused.value.status_code == 409 and refused.value.get_codes() == "queue_full"
        assert refused.value.extra == {"open_periods": 10, "limit": 12}

    def test_twelve_weeks_at_once_is_allowed_when_nothing_is_open_and_a_thirteenth_is_not(self):
        assert len(chain(quantity=12, limit=12)) == 12
        with pytest.raises(QueueFull):
            chain(quantity=1, open_periods=12, limit=12)


@pytest.mark.parametrize("quantity", [0, -1])
def test_a_quantity_below_one_is_a_mistake(quantity):
    with pytest.raises(ValueError):
        chain(quantity=quantity)


def test_a_period_of_no_length_is_a_mistake():
    with pytest.raises(ValueError):
        chain(period_days=0)

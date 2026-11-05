"""Unit under test: `credits.activity.CreditsActivitySink` with `DailyCredit`, and the streak bonuses it pays
(credits plan
T16, §5.6), against a real database and a clock the test moves.

Why: this is how studying becomes credits. The first activity of a learner's day must write the day and give the daily
credit once; a second the same day must give nothing; a streak must pay its weekly and monthly bonuses exactly once
however
the days arrive; and the day must be the learner's, not the server's. The spec's numbers are tested as numbers: day 7
pays
10, day 28 pays 20, a continuous 28 days earns at most 78.

Use cases:
- the first activity of a local day writes a streak day and gives 1 credit in a `daily` bucket that lasts 90 days; a
  second
  activity the same day, of any kind, gives nothing and writes nothing
- the day is the learner's: at 18:29Z an Indian learner is still on the old day and at 18:31Z on the new one; a
  learner in a
  zone with daylight saving gets the right day on the days the clocks change; a learner with no zone is on Asia/Kolkata
- a streak pays 10 more at every multiple of 7 and 10 more at every multiple of 28, each once: day 7 pays 10, day 14
  pays
  10, day 28 pays 20, day 35 pays 10, day 56 pays 20; over a continuous 28 days a learner earns 28 + 40 + 10 = 78
- activity sent again, or the same milestone reached twice, pays nothing more; the amounts come from the settings
- a streak that breaks starts a new run with new bonuses, and a run restarted after a gap earns its own day 7
- a failed sink-side write leaves no half-recorded day, so the next activity of the day still earns it
- the cached streak state follows the days
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from credits.activity import CreditsActivitySink
from support.clock import FakeClock

from credits.ledger import Ledger
from credits.models import CreditBucket, CreditSettings, CreditTransaction, StreakDay, StreakState
from lessons.activity import ActivityKind

pytestmark = pytest.mark.django_db

START = datetime(2026, 11, 5, 6, 0, tzinfo=UTC)  # 11:30 in India


@pytest.fixture
def clock():
    return FakeClock(START)


@pytest.fixture
def sink(clock):
    return CreditsActivitySink(ledger=Ledger(clock=clock))


def study(sink, user, instant, kind=ActivityKind.QUIZ_ATTEMPT):
    sink.record(user, kind, instant)


def earned(user, source=None) -> int:
    buckets = CreditBucket.objects.filter(user=user)
    return sum(b.amount_granted for b in (buckets.filter(source=source) if source else buckets))


def study_days(sink, clock, user, count, first=START):
    """Study once a day for `count` days from `first`, moving the clock with it."""
    for n in range(count):
        instant = first + timedelta(days=n)
        clock.set(instant)
        study(sink, user, instant)


class TestTheDailyCredit:
    def test_the_first_activity_of_a_day_writes_the_day_and_gives_a_credit_for_90_days(self, sink, user, clock):
        study(sink, user, START)

        assert list(StreakDay.objects.filter(user=user).values_list("local_date", "kind")) == [
            (date(2026, 11, 5), "active")
        ]
        bucket = CreditBucket.objects.get(user=user, source="daily")
        assert (bucket.amount_granted, bucket.expires_at) == (1, clock.now() + timedelta(days=90))
        assert CreditTransaction.objects.get(user=user).idempotency_key == f"daily:{user.pk}:2026-11-05"

    @pytest.mark.parametrize("kind", list(ActivityKind))
    def test_a_second_activity_the_same_day_of_any_kind_gives_nothing(self, sink, user, kind):
        study(sink, user, START)
        rows = CreditTransaction.objects.count()

        study(sink, user, START + timedelta(hours=3), kind)

        assert CreditTransaction.objects.count() == rows and StreakDay.objects.filter(user=user).count() == 1
        assert earned(user) == 1

    def test_the_same_event_sent_again_changes_nothing(self, sink, user):
        study(sink, user, START)
        study(sink, user, START)

        assert earned(user) == 1 and CreditTransaction.objects.count() == 1

    def test_the_amount_comes_from_the_settings(self, sink, user):
        CreditSettings.objects.update_or_create(pk=1, defaults={"daily_credits": 3, "bonus_valid_days": 10})

        study(sink, user, START)

        bucket = CreditBucket.objects.get(user=user)
        assert bucket.amount_granted == 3 and bucket.expires_at == START + timedelta(days=10)

    def test_a_day_with_a_daily_credit_of_zero_is_still_a_streak_day(self, sink, user):
        CreditSettings.objects.update_or_create(pk=1, defaults={"daily_credits": 0})

        study(sink, user, START)

        assert StreakDay.objects.filter(user=user).count() == 1 and not CreditBucket.objects.exists()


class TestTheLearnersOwnDay:
    def test_in_india_the_day_changes_at_18_30_utc(self, sink, user):
        study(sink, user, datetime(2026, 11, 5, 18, 29, tzinfo=UTC))  # 23:59 on the 5th
        study(sink, user, datetime(2026, 11, 5, 18, 31, tzinfo=UTC))  # 00:01 on the 6th

        assert list(
            StreakDay.objects.filter(user=user).order_by("local_date").values_list("local_date", flat=True)
        ) == [
            date(2026, 11, 5),
            date(2026, 11, 6),
        ]
        assert earned(user, "daily") == 2

    def test_a_learner_with_no_zone_is_on_india_time(self, sink, user):
        assert user.profile.timezone == ""

        study(sink, user, datetime(2026, 11, 5, 19, 0, tzinfo=UTC))

        assert StreakDay.objects.get(user=user).local_date == date(2026, 11, 6)

    def test_the_learners_own_zone_decides(self, sink, user):
        user.profile.timezone = "America/New_York"
        user.profile.save()

        study(sink, user, datetime(2026, 11, 5, 19, 0, tzinfo=UTC))

        assert StreakDay.objects.get(user=user).local_date == date(2026, 11, 5)

    def test_on_the_day_the_clocks_change_the_boundary_is_the_local_midnight(self, sink, user):
        user.profile.timezone = "America/New_York"
        user.profile.save()

        study(sink, user, datetime(2026, 3, 8, 4, 59, tzinfo=UTC))  # still the 7th
        study(sink, user, datetime(2026, 3, 8, 5, 0, tzinfo=UTC))  # the 8th, which is 23 hours long
        study(sink, user, datetime(2026, 3, 9, 3, 59, tzinfo=UTC))  # still the 8th: nothing new
        study(sink, user, datetime(2026, 3, 9, 4, 0, tzinfo=UTC))  # the 9th

        dates = list(StreakDay.objects.filter(user=user).order_by("local_date").values_list("local_date", flat=True))
        assert dates == [date(2026, 3, 7), date(2026, 3, 8), date(2026, 3, 9)]

    def test_the_streak_continues_across_the_clock_change(self, sink, user, clock):
        user.profile.timezone = "America/New_York"
        user.profile.save()
        first = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

        study_days(sink, clock, user, 3, first)  # 1, 2 and 3 November: a 25-hour day in the middle

        assert StreakState.objects.get(user=user).current_streak == 3


class TestTheStreakBonuses:
    def bonus_total(self, user):
        return earned(user, "weekly_streak") + earned(user, "monthly_streak")

    def test_day_seven_pays_ten(self, sink, user, clock):
        study_days(sink, clock, user, 6)
        assert self.bonus_total(user) == 0

        study_days(sink, clock, user, 1, START + timedelta(days=6))

        assert earned(user, "weekly_streak") == 10 and earned(user, "monthly_streak") == 0

    def test_day_fourteen_pays_ten_more(self, sink, user, clock):
        study_days(sink, clock, user, 14)

        assert earned(user, "weekly_streak") == 20 and earned(user, "monthly_streak") == 0

    def test_day_28_pays_20_the_week_and_the_month(self, sink, user, clock):
        study_days(sink, clock, user, 27)
        before = self.bonus_total(user)

        study_days(sink, clock, user, 1, START + timedelta(days=27))

        assert before == 30 and self.bonus_total(user) - before == 20
        assert earned(user, "weekly_streak") == 40 and earned(user, "monthly_streak") == 10

    def test_28_continuous_days_earn_78(self, sink, user, clock):
        study_days(sink, clock, user, 28)

        assert earned(user) == 78
        assert (earned(user, "daily"), earned(user, "weekly_streak"), earned(user, "monthly_streak")) == (28, 40, 10)

    def test_the_streak_keeps_counting_past_28(self, sink, user, clock):
        study_days(sink, clock, user, 35)
        assert earned(user, "weekly_streak") == 50 and earned(user, "monthly_streak") == 10

        study_days(sink, clock, user, 21, START + timedelta(days=35))  # to day 56

        assert earned(user, "weekly_streak") == 80 and earned(user, "monthly_streak") == 20
        assert StreakState.objects.get(user=user).current_streak == 56

    @pytest.mark.parametrize(
        ("day", "pays"), [(6, 0), (7, 10), (13, 0), (14, 10), (28, 20), (29, 0), (35, 10), (56, 20)]
    )
    def test_each_day_pays_what_the_spec_says(self, sink, user, clock, day, pays):
        study_days(sink, clock, user, day - 1)
        before = self.bonus_total(user)

        study_days(sink, clock, user, 1, START + timedelta(days=day - 1))

        assert self.bonus_total(user) - before == pays

    def test_the_bonus_buckets_last_90_days(self, sink, user, clock):
        study_days(sink, clock, user, 28)

        bonus = CreditBucket.objects.filter(user=user, source__in=["weekly_streak", "monthly_streak"])
        assert bonus.count() == 5 and all(b.expires_at == b.created_at + timedelta(days=90) for b in bonus)

    def test_a_bonus_is_paid_once_however_often_the_milestone_is_reached(self, sink, user, clock):
        study_days(sink, clock, user, 7)
        study(sink, user, START + timedelta(days=6, hours=2))  # the same day again
        study(sink, user, START + timedelta(days=6))
        sink.pay_milestones(user, date(2026, 11, 11))  # asked again directly

        assert earned(user, "weekly_streak") == 10

    def test_the_amounts_come_from_the_settings(self, sink, user, clock):
        CreditSettings.objects.update_or_create(pk=1, defaults={"weekly_streak_bonus": 5, "monthly_streak_bonus": 2})

        study_days(sink, clock, user, 28)

        assert earned(user, "weekly_streak") == 20 and earned(user, "monthly_streak") == 2

    def test_a_streak_that_breaks_starts_a_new_run_with_its_own_bonuses(self, sink, user, clock):
        study_days(sink, clock, user, 7)  # days 1 to 7: pays day 7
        study_days(sink, clock, user, 7, START + timedelta(days=9))  # a gap of two days, then 7 more

        assert earned(user, "weekly_streak") == 20  # each run earned its own day 7
        keys = CreditTransaction.objects.filter(user=user, idempotency_key__startswith="streak:")
        assert len({k.idempotency_key.split(":")[2] for k in keys}) == 2  # two run start dates

    def test_the_cached_state_follows_the_days(self, sink, user, clock):
        study_days(sink, clock, user, 3)

        state = StreakState.objects.get(user=user)
        assert (state.current_streak, state.longest_streak, state.run_started_on, state.last_day) == (
            3,
            3,
            date(2026, 11, 5),
            date(2026, 11, 7),
        )

        study_days(sink, clock, user, 1, START + timedelta(days=6))  # a gap, then a new run of one

        state.refresh_from_db()
        assert (state.current_streak, state.longest_streak, state.run_started_on) == (1, 3, date(2026, 11, 11))


class TestAFailureLeavesNothingHalfDone:
    def test_a_failed_credit_rolls_the_day_back_so_the_next_activity_earns_it(self, user, clock, monkeypatch):
        sink = CreditsActivitySink(ledger=Ledger(clock=clock))
        original = sink.daily.grant_for

        def broken(*args, **kwargs):
            raise RuntimeError("the database went away")

        monkeypatch.setattr(sink.daily, "grant_for", broken)
        with pytest.raises(RuntimeError):
            study(sink, user, START)
        assert not StreakDay.objects.exists()

        monkeypatch.setattr(sink.daily, "grant_for", original)
        study(sink, user, START + timedelta(minutes=5))

        assert StreakDay.objects.count() == 1 and earned(user, "daily") == 1

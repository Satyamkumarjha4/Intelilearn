"""Unit under test: `credits.notices.ExpiryNotices` and its window policies (credits plan §5.10).

Why: a learner who loses credits without being told feels cheated, and one nagged about credits that are months from
lapsing stops reading the banner. The rules are per source (a week of Pro is short, a purchase is long, signup credits
never lapse), counted in the learner's own days (the last day is the last day *they* can use the credits), and credits
that lapse on one day are one message, not five. Nothing is stored: a notice is computed from the buckets each time, so
it can never be stale or out of step with the wallet.

Use cases:
- signup, admin and refund credits never raise a notice; credits that never expire, and credits that have already
  lapsed, are empty, or were taken back, are not counted
- weekly subscription credits: nothing 3 days before the end, a notice from 2 days before, daily, to the last day
- monthly and Pro Plus credits: a notice in the last 7 days only
- bonus credits (daily, weekly and monthly streak): a notice in the last 7 days only
- purchased credits: a notice at 30 days left shown for 3 days, nothing in between, and a final one in the last 7
- credits that lapse on the same local day are summed into one notice, however many sources; a day with only
  sources that never notify says nothing; notices come soonest first
- the days are the learner's: the same bucket is on its last day in one zone and a day away in another, and a bucket
  that lapses at local midnight has the day before as its last day
- the words: "This is your last day to use 40 credits.", tomorrow, and a dated message; one credit is singular
- the windows are the editable settings, not constants
- reading through the database: another learner's credits are not counted, the learner's zone is the one from their
  profile (Asia/Kolkata when unset), a bought plan's weekly or monthly kind is found from its period, and counting
  gives the same number as listing
"""

from datetime import UTC, datetime, timedelta

import pytest

from credits.models import CreditBucket, CreditSettings
from credits.notices import ExpiryNotices, NoticeBucket
from credits.plans.desk import PurchaseDesk
from credits.plans.fulfilment import PlanFulfilment
from credits.plans.seed import PlanSeed

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
SETTINGS = CreditSettings()  # the spec's defaults, without touching the database


def bucket(source, days, remaining=40, plan_key="", hours=None):
    """Credits of `source` that lapse `days` days (and `hours`) from NOW; on day 0 that is an hour from now, as credits
    that lapse this very instant are already gone."""
    hours = (1 if days == 0 else 0) if hours is None else hours
    return NoticeBucket(source, remaining, NOW + timedelta(days=days, hours=hours), plan_key)


def notices(*buckets, zone="UTC", now=NOW):
    return ExpiryNotices().of(list(buckets), now, zone, SETTINGS)


def days_left(*buckets):
    return [n.days_left for n in notices(*buckets)]


class TestWhoIsNeverTold:
    @pytest.mark.parametrize("source", ["signup", "admin_grant", "refund"])
    def test_signup_admin_and_refund_credits_raise_no_notice(self, source):
        assert notices(bucket(source, 1)) == []

    def test_credits_that_never_expire_raise_no_notice(self):
        assert notices(NoticeBucket("daily", 40, None)) == []

    def test_a_subscription_bucket_with_no_known_plan_raises_no_notice(self):
        assert notices(bucket("subscription", 1)) == []


class TestWeeklySubscription:
    def test_nothing_three_days_before_the_end(self):
        assert notices(bucket("subscription", 3, plan_key="weekly_pro")) == []

    @pytest.mark.parametrize("days", [2, 1, 0])
    def test_a_notice_from_two_days_before_the_end_to_the_last_day(self, days):
        assert days_left(bucket("subscription", days, plan_key="weekly_pro")) == [days]


class TestMonthlyAndProPlus:
    @pytest.mark.parametrize("plan_key", ["monthly_pro", "pro_plus"])
    def test_a_notice_only_in_the_last_seven_days(self, plan_key):
        assert notices(bucket("subscription", 8, plan_key=plan_key)) == []
        assert days_left(bucket("subscription", 7, plan_key=plan_key)) == [7]
        assert days_left(bucket("subscription", 0, plan_key=plan_key)) == [0]


class TestBonusCredits:
    @pytest.mark.parametrize("source", ["daily", "weekly_streak", "monthly_streak"])
    def test_a_notice_only_in_the_last_seven_days(self, source):
        assert notices(bucket(source, 8)) == []
        assert days_left(bucket(source, 7)) == [7]
        assert days_left(bucket(source, 1)) == [1]


class TestPurchasedCredits:
    def test_nothing_at_31_days(self):
        assert notices(bucket("purchase", 31)) == []

    @pytest.mark.parametrize("days", [30, 29, 28])
    def test_the_first_notice_at_30_days_left_is_shown_for_three_days(self, days):
        assert days_left(bucket("purchase", days)) == [days]

    @pytest.mark.parametrize("days", [27, 20, 8])
    def test_nothing_between_the_first_notice_and_the_last_week(self, days):
        assert notices(bucket("purchase", days)) == []

    @pytest.mark.parametrize("days", [7, 3, 0])
    def test_a_final_notice_in_the_last_seven_days(self, days):
        assert days_left(bucket("purchase", days)) == [days]


class TestOneMessagePerDay:
    def test_credits_that_lapse_on_the_same_day_are_summed(self):
        found = notices(
            bucket("daily", 2, remaining=25),
            bucket("weekly_streak", 2, remaining=15, hours=3),
        )

        assert [(n.credits, n.text) for n in found] == [(40, "40 credits will run out on Saturday 7 November.")]

    def test_the_last_day_says_so(self):
        found = notices(bucket("daily", 0, remaining=25, hours=2), bucket("weekly_streak", 0, remaining=15, hours=3))

        assert [n.text for n in found] == ["This is your last day to use 40 credits."]

    def test_a_source_that_never_notifies_is_counted_in_a_day_that_does(self):
        found = notices(bucket("daily", 3, remaining=10), bucket("admin_grant", 3, remaining=5))

        assert [n.credits for n in found] == [15]

    def test_a_day_with_only_sources_that_never_notify_says_nothing(self):
        assert notices(bucket("admin_grant", 3, remaining=5), bucket("refund", 3, remaining=5)) == []

    def test_different_days_are_different_notices_soonest_first(self):
        found = notices(
            bucket("daily", 5, remaining=3), bucket("daily", 1, remaining=2), bucket("daily", 3, remaining=1)
        )

        assert [(n.days_left, n.credits) for n in found] == [(1, 2), (3, 1), (5, 3)]


class TestTheLearnersDay:
    def test_the_same_bucket_is_on_its_last_day_in_one_zone_and_a_day_away_in_another(self):
        lapses = bucket("daily", 0, hours=8)  # 20:00 UTC today, which is 01:30 tomorrow in Kolkata

        assert days_left(lapses) == [0]
        assert [n.days_left for n in notices(lapses, zone="Asia/Kolkata")] == [1]

    def test_a_bucket_that_lapses_at_local_midnight_has_the_day_before_as_its_last_day(self):
        midnight = NoticeBucket("daily", 40, datetime(2026, 11, 6, 0, 0, tzinfo=UTC))

        found = notices(midnight)

        assert [(n.days_left, n.expires_on.isoformat()) for n in found] == [(0, "2026-11-05")]

    def test_a_notice_names_the_day_it_is_about(self):
        found = notices(bucket("daily", 3))

        assert (found[0].id, found[0].expires_on.isoformat()) == ("expiry-2026-11-08", "2026-11-08")


class TestTheWords:
    def test_tomorrow(self):
        assert [n.text for n in notices(bucket("daily", 1))] == ["40 credits will run out tomorrow."]

    def test_one_credit_is_singular(self):
        assert [n.text for n in notices(bucket("daily", 0, remaining=1, hours=1))] == [
            "This is your last day to use 1 credit."
        ]
        assert [n.text for n in notices(bucket("daily", 4, remaining=1))] == [
            "1 credit will run out on Monday 9 November."
        ]

    def test_no_internal_word_reaches_a_learner(self):
        found = notices(bucket("purchase", 30), bucket("daily", 0), bucket("subscription", 1, plan_key="weekly_pro"))

        text = " ".join(n.text for n in found).lower()
        assert not any(word in text for word in ("bucket", "ledger", "hold", "reserve", "source"))


class TestTheWindowsAreSettings:
    def test_a_longer_weekly_window_is_followed(self):
        wider = CreditSettings(weekly_notice_days=4)

        found = ExpiryNotices().of([bucket("subscription", 4, plan_key="weekly_pro")], NOW, "UTC", wider)

        assert [n.days_left for n in found] == [4]

    def test_the_purchased_windows_are_followed(self):
        custom = CreditSettings(purchased_notice_days=20, purchased_notice_show_days=2, purchased_final_notice_days=3)
        expiry = ExpiryNotices()

        def seen(days):
            return [n.days_left for n in expiry.of([bucket("purchase", days)], NOW, "UTC", custom)]

        assert (seen(21), seen(20), seen(19), seen(18), seen(4), seen(3)) == ([], [20], [19], [], [], [3])


@pytest.mark.django_db
class TestFromTheDatabase:
    @pytest.fixture
    def expiry(self, clock):
        return ExpiryNotices(clock=clock)

    def test_it_counts_live_credits_and_leaves_out_the_rest(self, expiry, give, clock, user, other_user):
        give(user, 5, source="daily", days=2)  # counted
        give(user, 7, source="daily", days=None)  # never lapses
        give(other_user, 9, source="daily", days=2)  # someone else's
        give(user, 3, source="daily", days=2)  # used up below
        CreditBucket.objects.filter(user=user, amount_granted=3).update(amount_remaining=0)
        give(user, 4, source="daily", days=2)  # taken back below
        CreditBucket.objects.filter(user=user, amount_granted=4).update(revoked_at=clock.now())
        give(user, 6, source="daily", days=-1)  # already lapsed

        assert [n.credits for n in expiry.for_user(user)] == [5]

    def test_the_learners_zone_is_the_one_in_their_profile(self, expiry, give, clock, user):
        give(user, 5, source="daily", days=1)
        CreditBucket.objects.update(expires_at=datetime(2026, 11, 5, 20, 0, tzinfo=UTC))  # 01:30 tomorrow in Kolkata

        assert [n.days_left for n in expiry.for_user(user)] == [1]  # Kolkata when nothing is set

        user.profile.timezone = "UTC"
        user.profile.save()

        assert [n.days_left for n in expiry.for_user(user)] == [0]

    def test_a_bought_weekly_plan_is_found_from_its_period(self, expiry, ledger, clock, user):
        PlanSeed().apply()
        desk, fulfilment = PurchaseDesk(ledger=ledger), PlanFulfilment(ledger=ledger)
        fulfilment.fulfil(desk.open(user, "weekly_pro"))
        user.profile.timezone = "UTC"
        user.profile.save()

        clock.advance(days=4)
        assert expiry.for_user(user) == []  # three days left

        clock.advance(days=1)
        assert [(n.days_left, n.credits) for n in expiry.for_user(user)] == [(2, 100)]

    def test_a_bought_monthly_plan_waits_for_the_last_week(self, expiry, ledger, clock, user):
        PlanSeed().apply()
        PlanFulfilment(ledger=ledger).fulfil(PurchaseDesk(ledger=ledger).open(user, "monthly_pro"))
        user.profile.timezone = "UTC"
        user.profile.save()

        clock.advance(days=20)
        assert expiry.for_user(user) == []  # eight days left

        clock.advance(days=1)
        assert [n.days_left for n in expiry.for_user(user)] == [7]

    def test_counting_gives_the_number_listed(self, expiry, give, user):
        give(user, 5, source="daily", days=2)
        give(user, 5, source="daily", days=4)
        give(user, 5, source="daily", days=40)

        assert expiry.count(user) == len(expiry.for_user(user)) == 2

    def test_a_learner_with_no_credits_has_no_notices(self, expiry, user):
        assert expiry.for_user(user) == []
        assert expiry.count(user) == 0

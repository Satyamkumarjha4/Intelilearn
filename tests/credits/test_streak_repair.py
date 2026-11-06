"""Unit under test: `credits.earning.repair.StreakRepairService` (credits plan T17, D2) and `GET /api/credits/streak`,
`POST /api/credits/streak/repair`.

Why: a repair spends a credit to save a streak, and it is the one earning feature a learner can pay to bend. The
rules are
what stop "skip every other day and repair": only yesterday, only after a streak day, one in any 7 days and three in
any 28,
counted from the day each was made so that breaking the streak cannot reset them. A repaired day keeps the streak but
earns
no daily credit, and the bonus it may complete is paid once.

Use cases:
- a missed yesterday after a streak day is repaired for 1 credit: a repaired day is written, the credit is spent, the
  streak
  runs through it and the daily credit is not given for it
- the repair can complete a milestone (day 7), which is paid then and never again
- yesterday present, or the day before it missing, or no days at all, is `409 nothing_to_repair` and costs nothing
- a second repair in 7 days and a fourth in 28 are `409 repair_limit` and cost nothing; the rolling windows let go of
  old
  repairs; a streak that broke and restarted does not reset them
- too few credits is `402 insufficient_credits`, nothing is written, and the learner can try again with more
- repairing the same day twice, or sending the request twice, charges once
- the day is the learner's own: on the learner's local day T the day T - 1 is repaired
- the streak answer gives the current and longest streak, the run's start, today's state, the last 28 days, the next
  bonus
  and the repair outlook (available, the day, the cost, the repairs left this week and month, why not)
- both need a signed-in learner; a learner sees only their own; a read changes nothing
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from support.clock import FakeClock

from credits.activity import CreditsActivitySink
from credits.earning.repair import NothingToRepair, RepairLimitReached, StreakRepairService
from credits.ledger import Ledger
from credits.models import CreditBucket, CreditTransaction, StreakDay, StreakState
from credits.refusals import InsufficientCredits
from lessons.activity import ActivityKind

pytestmark = pytest.mark.django_db

NOON = datetime(2026, 11, 20, 6, 0, tzinfo=UTC)  # 11:30 on 20 November in India
DAY = timedelta(days=1)


@pytest.fixture
def clock():
    return FakeClock(NOON)


@pytest.fixture
def ledger(clock):
    return Ledger(clock=clock)


@pytest.fixture
def sink(ledger):
    return CreditsActivitySink(ledger=ledger)


@pytest.fixture
def service(ledger):
    return StreakRepairService(ledger=ledger)


def study_on(sink, user, *offsets):
    """Be active on the days `offsets` from the 20th (0 is today, -1 yesterday…)."""
    for n in offsets:
        sink.record(user, ActivityKind.QUIZ_ATTEMPT, NOON + n * DAY)


def dates(user) -> list[date]:
    return list(StreakDay.objects.filter(user=user).order_by("local_date").values_list("local_date", flat=True))


def credits_of(ledger, user) -> int:
    return ledger.balance(user)


def have_days(user, *offsets):
    """Streak days written straight into the table (no daily credit), `offsets` from the 20th."""
    for n in offsets:
        StreakDay.objects.create(user=user, local_date=date(2026, 11, 20) + n * DAY, kind="active", created_at=NOON)


def repaired_before(user, *, day: int, on: int):
    """A repair already made: of the day `day`, on the day `on`, both as offsets from the 20th."""
    StreakDay.objects.create(
        user=user,
        local_date=date(2026, 11, 20) + day * DAY,
        kind="repaired",
        repaired_on=date(2026, 11, 20) + on * DAY,
        created_at=NOON,
    )


class TestRepairing:
    def test_a_missed_yesterday_after_a_streak_day_is_repaired_for_a_credit(self, service, sink, ledger, user):
        study_on(sink, user, -3, -2)  # yesterday (-1) missed
        ledger.grant(user, "signup", 10, "welcome")
        before = credits_of(ledger, user)

        result = service.repair(user)

        assert result.day == date(2026, 11, 19) and result.cost == 1
        repaired = StreakDay.objects.get(user=user, local_date=date(2026, 11, 19))
        assert (repaired.kind, repaired.repaired_on) == ("repaired", date(2026, 11, 20))
        assert credits_of(ledger, user) == before - 1
        row = CreditTransaction.objects.get(user=user, type="repair")
        assert (row.amount, row.action) == (-1, "streak_repair")

    def test_the_streak_runs_through_the_repaired_day(self, service, sink, ledger, user):
        study_on(sink, user, -3, -2, 0)
        ledger.grant(user, "signup", 10, "welcome")

        service.repair(user)

        state = StreakState.objects.get(user=user)
        assert (state.current_streak, state.run_started_on) == (4, date(2026, 11, 17))

    def test_a_repaired_day_earns_no_daily_credit(self, service, sink, ledger, user):
        study_on(sink, user, -3, -2)
        ledger.grant(user, "signup", 10, "welcome")
        daily_before = CreditBucket.objects.filter(user=user, source="daily").count()

        service.repair(user)

        assert CreditBucket.objects.filter(user=user, source="daily").count() == daily_before
        assert not CreditTransaction.objects.filter(idempotency_key=f"daily:{user.pk}:2026-11-19").exists()

    def test_a_repair_that_completes_day_seven_pays_the_bonus_once(self, service, sink, ledger, user):
        study_on(sink, user, -7, -6, -5, -4, -3, -2)  # six days, yesterday missed
        ledger.grant(user, "signup", 10, "welcome")
        assert not CreditBucket.objects.filter(user=user, source="weekly_streak").exists()

        service.repair(user)  # the run is seven days long now

        weekly = CreditBucket.objects.filter(user=user, source="weekly_streak")
        assert [b.amount_granted for b in weekly] == [10]
        sink.pay_milestones(user, date(2026, 11, 20))  # looked at again: nothing more
        assert CreditBucket.objects.filter(user=user, source="weekly_streak").count() == 1

    def test_the_repair_result_carries_the_new_streak_and_what_it_paid(self, service, sink, ledger, user):
        study_on(sink, user, -7, -6, -5, -4, -3, -2)
        ledger.grant(user, "signup", 10, "welcome")

        result = service.repair(user)

        assert result.streak.current == 7 and result.bonus == 10


class TestWhatCannotBeRepaired:
    def test_yesterday_present_is_nothing_to_repair(self, service, sink, ledger, user):
        study_on(sink, user, -2, -1)
        ledger.grant(user, "signup", 10, "welcome")
        rows = CreditTransaction.objects.count()

        with pytest.raises(NothingToRepair) as refused:
            service.repair(user)

        assert refused.value.status_code == 409 and refused.value.get_codes() == "nothing_to_repair"
        assert CreditTransaction.objects.count() == rows

    def test_a_missed_day_after_a_missed_day_is_nothing_to_repair(self, service, sink, ledger, user):
        study_on(sink, user, -5)
        ledger.grant(user, "signup", 10, "welcome")

        with pytest.raises(NothingToRepair):
            service.repair(user)

    def test_a_learner_who_has_never_studied_has_nothing_to_repair(self, service, ledger, user):
        ledger.grant(user, "signup", 10, "welcome")

        with pytest.raises(NothingToRepair):
            service.repair(user)

    def test_only_yesterday_never_an_older_gap(self, service, sink, ledger, user):
        study_on(sink, user, -6, -5, -2, -1)  # gaps at -4 and -3
        ledger.grant(user, "signup", 10, "welcome")

        with pytest.raises(NothingToRepair):
            service.repair(user)


class TestTheLimits:
    @pytest.fixture(autouse=True)
    def funded(self, ledger, user):
        ledger.grant(user, "signup", 50, "welcome")

    def test_a_second_repair_in_seven_days_is_refused_and_costs_nothing(self, service, ledger, user):
        have_days(user, -2)  # yesterday missed after a streak day
        repaired_before(user, day=-4, on=-3)
        balance = ledger.balance(user)

        with pytest.raises(RepairLimitReached) as refused:
            service.repair(user)

        assert refused.value.status_code == 409 and refused.value.get_codes() == "repair_limit"
        assert ledger.balance(user) == balance

    def test_a_repair_made_earlier_today_counts_too(self, service, user):
        have_days(user, -2)
        repaired_before(user, day=-9, on=0)

        with pytest.raises(RepairLimitReached):
            service.repair(user)

    def test_the_week_lets_go_after_seven_days(self, service, user):
        have_days(user, -2)
        repaired_before(user, day=-9, on=-7)

        assert service.repair(user).day == date(2026, 11, 19)

    def test_the_fourth_repair_in_28_days_is_refused_even_with_a_free_week(self, service, user):
        have_days(user, -2)
        for n in (-8, -15, -22):
            repaired_before(user, day=n - 1, on=n)

        with pytest.raises(RepairLimitReached):
            service.repair(user)

    def test_the_month_lets_go_after_28_days(self, service, user):
        have_days(user, -2)
        for n in (-8, -15, -28):
            repaired_before(user, day=n - 1, on=n)

        assert service.repair(user).day == date(2026, 11, 19)

    def test_breaking_the_streak_does_not_reset_the_limits(self, service, user):
        have_days(user, *range(-40, -30))  # a long run that ended a month ago
        have_days(user, -2)  # a new one
        repaired_before(user, day=-4, on=-3)

        with pytest.raises(RepairLimitReached):
            service.repair(user)


class TestPaying:
    def test_too_few_credits_is_402_and_writes_nothing(self, service, sink, ledger, user):
        study_on(sink, user, -3, -2)
        ledger.debit(user, ledger.balance(user), "x", "spend-all")
        rows, days = CreditTransaction.objects.count(), StreakDay.objects.count()

        with pytest.raises(InsufficientCredits) as refused:
            service.repair(user)

        assert (refused.value.required, refused.value.available) == (1, 0)
        assert CreditTransaction.objects.count() == rows and StreakDay.objects.count() == days

    def test_the_learner_can_try_again_with_more_credits(self, service, sink, ledger, user):
        study_on(sink, user, -3, -2)
        ledger.debit(user, ledger.balance(user), "x", "spend-all")
        with pytest.raises(InsufficientCredits):
            service.repair(user)

        ledger.grant(user, "admin_grant", 5, "top-up")

        assert service.repair(user).day == date(2026, 11, 19)

    def test_the_same_request_twice_charges_once(self, service, sink, ledger, user):
        study_on(sink, user, -3, -2)
        ledger.grant(user, "signup", 10, "welcome")

        service.repair(user)
        with pytest.raises(NothingToRepair):  # yesterday is there now
            service.repair(user)

        assert CreditTransaction.objects.filter(user=user, type="repair").count() == 1

    def test_the_cost_is_a_setting(self, service, sink, ledger, user):
        from credits.models import CreditSettings

        CreditSettings.objects.update_or_create(pk=1, defaults={"repair_cost": 3})
        study_on(sink, user, -3, -2)
        ledger.grant(user, "signup", 10, "welcome")
        before = ledger.balance(user)

        service.repair(user)

        assert ledger.balance(user) == before - 3


class TestTheLearnersDay:
    def test_it_repairs_the_day_before_the_learners_today(self, ledger, sink, clock, user):
        user.profile.timezone = "America/New_York"
        user.profile.save()
        ledger.grant(user, "signup", 10, "welcome")
        clock.set(datetime(2026, 11, 20, 3, 0, tzinfo=UTC))  # still the 19th in New York
        sink.record(user, ActivityKind.QUIZ_ATTEMPT, datetime(2026, 11, 17, 15, 0, tzinfo=UTC))
        sink.record(user, ActivityKind.QUIZ_ATTEMPT, datetime(2026, 11, 16, 15, 0, tzinfo=UTC))

        result = StreakRepairService(ledger=ledger).repair(user)

        assert result.day == date(2026, 11, 18)  # today is the 19th there, so the 18th was missed


class TestTheEndpoints:
    STREAK, REPAIR = "/api/credits/streak", "/api/credits/streak/repair"

    @staticmethod
    def study(user, *ago):
        """Study `n` days ago for each n in `ago`, by the real clock the views use."""
        now = datetime.now(UTC)
        for n in ago:
            CreditsActivitySink().record(user, ActivityKind.QUIZ_ATTEMPT, now - n * DAY)

    def test_both_need_a_signed_in_learner(self, api_client):
        assert api_client.get(self.STREAK).status_code == 401
        assert api_client.post(self.REPAIR).status_code == 401

    def test_a_new_learner_has_no_streak_and_the_read_changes_nothing(self, signed_in_client, user):
        body = signed_in_client.get(self.STREAK).json()

        assert body["current"] == 0 and body["longest"] == 0 and body["alive"] is False
        assert body["today"]["done"] is False and body["repair"]["available"] is False
        assert body["repair"]["reason"] == "nothing_to_repair" and body["repair"]["day"] is None
        assert not StreakDay.objects.exists() and not CreditTransaction.objects.exists()

    def test_it_gives_the_streak_the_last_28_days_the_next_bonus_and_the_repair_outlook(self, signed_in_client, user):
        self.study(user, 3, 2, 0)  # yesterday missed

        body = signed_in_client.get(self.STREAK).json()

        assert body["current"] == 1 and body["longest"] == 2 and body["alive"] is True
        assert body["today"]["done"] is True
        assert len(body["days"]) == 28 and body["days"][-1]["state"] == "active"
        assert [d["state"] for d in body["days"][-4:]] == ["active", "active", "missed", "active"]
        assert body["next_bonus"] == {"streak_day": 7, "credits": 10, "days_to_go": 6}
        repair = body["repair"]
        assert repair["available"] is True and repair["cost"] == 1 and repair["reason"] is None
        assert (repair["left_week"], repair["left_month"]) == (1, 3)

    def test_the_bonus_on_a_multiple_of_28_is_the_week_and_the_month(self, signed_in_client, user):
        self.study(user, *range(0, 22))  # a run of 22 days: the next bonus is day 28

        body = signed_in_client.get(self.STREAK).json()

        assert body["current"] == 22
        assert body["next_bonus"] == {"streak_day": 28, "credits": 20, "days_to_go": 6}

    def test_repairing_over_the_endpoint_spends_a_credit_and_returns_the_new_streak(self, signed_in_client, user):
        self.study(user, 3, 2)
        ledger = Ledger()
        before = ledger.balance(user)

        response = signed_in_client.post(self.REPAIR)

        assert response.status_code == 200
        body = response.json()
        assert body["cost"] == 1 and body["streak"]["current"] == 3 and body["bonus"] == 0
        assert ledger.balance(user) == before - 1
        assert StreakDay.objects.filter(user=user, kind="repaired").count() == 1

    def test_nothing_to_repair_is_409(self, signed_in_client, user):
        response = signed_in_client.post(self.REPAIR)

        assert response.status_code == 409 and response.json()["code"] == "nothing_to_repair"

    def test_a_second_repair_in_a_week_is_409_repair_limit(self, signed_in_client, user):
        self.study(user, 2)
        today = datetime.now(UTC).date()
        StreakDay.objects.create(
            user=user,
            local_date=today - 20 * DAY,
            kind="repaired",
            repaired_on=today - 3 * DAY,
            created_at=datetime.now(UTC),
        )

        response = signed_in_client.post(self.REPAIR)

        assert response.status_code == 409 and response.json()["code"] == "repair_limit"

    def test_too_few_credits_is_402(self, signed_in_client, user):
        self.study(user, 3, 2)
        ledger = Ledger()
        ledger.debit(user, ledger.balance(user), "x", "spend-all")

        response = signed_in_client.post(self.REPAIR)

        assert response.status_code == 402
        assert response.json()["code"] == "insufficient_credits" and response.json()["required"] == 1

    def test_another_learners_streak_is_not_shown(self, signed_in_client, other_user):
        self.study(other_user, 0)

        assert signed_in_client.get(self.STREAK).json()["current"] == 0

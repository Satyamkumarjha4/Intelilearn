"""Unit under test: `credits.plans.desk.PurchaseDesk` (opening a purchase) and `credits.plans.fulfilment.PlanFulfilment`
(turning a purchase into credits), and the periods they make (credits plan T19, T20, §5.7, spec §5).

Why: this is the only path that grants plan credits, and 10.6's payment handling will call it. The promises are the
spec's:
one-time credits last a year and can be spent at once; several weeks drip one at a time and are never granted all at
once; a
second plan queues behind the first; and nothing is granted twice however often fulfilment is asked for. Throughout, the
ledger must still add up.

Use cases:
- one-time credits make one bucket that lasts 365 days, tagged with the purchase, spendable at once, on top of any plan;
  the amount asked for is checked against the smallest and largest
- three Weekly Pro weeks make three consecutive periods, and 100 credits are granted as each one starts, never 300 at
  once
- a Monthly Pro bought during a week queues and starts when the week ends; buying the same plan again queues too
- at most 12 periods may be open; the 13th is refused when the purchase is opened, and nothing is created
- credits are spendable the moment a period starts, without any job running; a period nobody used is recorded as granted
  and then expired
- fulfilling twice grants once; a purchase that was voided cannot be fulfilled; a purchase made by an administrator is
  marked, free, and says why
- the ledger equals the buckets after every step; the buckets of a purchase carry its id
- the plan, the quantity and the amount are decided by the server: an unknown or switched-off plan is refused
"""

from datetime import timedelta

import pytest

from credits.audit import LedgerAudit
from credits.models import CreditBucket, CreditTransaction, Plan, PlanPeriod, PlanPurchase
from credits.plans.desk import PurchaseDesk
from credits.plans.errors import InvalidPlanRequest, QueueFull
from credits.plans.fulfilment import PlanFulfilment
from credits.plans.seed import PlanSeed

pytestmark = pytest.mark.django_db

DAY = timedelta(days=1)


@pytest.fixture(autouse=True)
def plans(db):
    PlanSeed().apply()


@pytest.fixture
def desk(ledger):
    return PurchaseDesk(ledger=ledger)


@pytest.fixture
def fulfilment(ledger):
    return PlanFulfilment(ledger=ledger)


@pytest.fixture
def buy(desk, fulfilment):
    def _buy(user, plan, **kwargs):
        return fulfilment.fulfil(desk.open(user, plan, **kwargs))

    return _buy


def periods(user):
    return list(PlanPeriod.objects.filter(user=user).order_by("starts_at", "position"))


def sound(user):
    assert LedgerAudit().check(user).ok


class TestOneTimeCredits:
    def test_it_makes_a_bucket_that_lasts_a_year_and_can_be_spent_at_once(self, buy, ledger, user, clock):
        done = buy(user, "one_time", credits=250)

        purchase = done.purchase
        bucket = CreditBucket.objects.get(user=user, source="purchase")
        assert (bucket.amount_granted, bucket.expires_at, bucket.purchase_id) == (
            250,
            clock.now() + 365 * DAY,
            purchase.pk,
        )
        assert ledger.balance(user) == 250 and periods(user) == []
        ledger.debit(user, 250, "x", "spend-all")  # spendable immediately
        sound(user)

    def test_the_purchase_records_what_it_cost_and_that_it_is_done(self, buy, user, clock):
        purchase = buy(user, "one_time", credits=250).purchase

        assert (purchase.status, purchase.credits, purchase.amount_paise, purchase.quantity) == (
            "fulfilled",
            250,
            25000,
            1,
        )
        assert (purchase.source, purchase.fulfilled_at, purchase.created_at) == ("payment", clock.now(), clock.now())

    def test_it_goes_on_top_of_a_plan(self, buy, ledger, user):
        buy(user, "monthly_pro")

        buy(user, "one_time", credits=40)

        assert ledger.balance(user) == 500 + 40
        sound(user)

    @pytest.mark.parametrize("credits", [9, 5001, 0, 12.5, "50", None])
    def test_an_amount_outside_the_limits_is_refused_and_nothing_is_made(self, desk, user, credits):
        with pytest.raises(InvalidPlanRequest) as refused:
            desk.open(user, "one_time", credits=credits)

        assert refused.value.get_codes() == "invalid_amount" and not PlanPurchase.objects.exists()

    def test_the_limits_are_the_credit_settings(self, desk, user):
        from credits.models import CreditSettings

        CreditSettings.objects.update_or_create(pk=1, defaults={"min_one_time_credits": 50, "max_one_time_credits": 60})

        assert desk.open(user, "one_time", credits=50).credits == 50
        with pytest.raises(InvalidPlanRequest):
            desk.open(user, "one_time", credits=49)
        with pytest.raises(InvalidPlanRequest):
            desk.open(user, "one_time", credits=61)

    def test_the_validity_is_a_setting(self, buy, user, clock):
        from credits.models import CreditSettings

        CreditSettings.objects.update_or_create(pk=1, defaults={"purchased_valid_days": 100})

        buy(user, "one_time", credits=10)

        assert CreditBucket.objects.get(user=user).expires_at == clock.now() + 100 * DAY


class TestWeeklyProDrips:
    def test_three_weeks_make_three_consecutive_periods(self, buy, user, clock):
        done = buy(user, "weekly_pro", quantity=3)

        made = periods(user)
        assert len(done.periods) == 3 and [p.position for p in made] == [1, 2, 3]
        assert [p.starts_at for p in made] == [clock.now() + n * 7 * DAY for n in range(3)]
        assert all(p.ends_at - p.starts_at == 7 * DAY and p.credits == 100 for p in made)
        assert done.purchase.amount_paise == 3 * 4900 and done.purchase.credits == 0

    def test_only_the_first_week_is_granted_and_never_300_at_once(self, buy, ledger, user):
        buy(user, "weekly_pro", quantity=3)

        assert ledger.balance(user) == 100
        assert [p.status for p in periods(user)] == ["active", "queued", "queued"]
        assert CreditBucket.objects.filter(user=user, source="subscription").count() == 1
        sound(user)

    def test_each_week_is_granted_as_it_starts_with_its_own_expiry(self, buy, ledger, user, clock):
        buy(user, "weekly_pro", quantity=3)
        first = clock.now()

        clock.set(first + 7 * DAY)
        ledger.grant(user, "admin_grant", 1, "touch-1")
        assert ledger.balance(user) == 100 + 1  # the first week's 100 lapsed, the second week's 100 began

        clock.set(first + 14 * DAY)
        ledger.grant(user, "admin_grant", 1, "touch-2")
        buckets = CreditBucket.objects.filter(user=user, source="subscription").order_by("created_at")
        assert [(b.amount_granted, b.expires_at) for b in buckets] == [
            (100, first + 7 * DAY),
            (100, first + 14 * DAY),
            (100, first + 21 * DAY),
        ]
        sound(user)

    def test_the_purchase_id_is_on_every_bucket_of_the_purchase(self, buy, ledger, user, clock):
        purchase = buy(user, "weekly_pro", quantity=2).purchase
        clock.advance(days=7)
        ledger.grant(user, "admin_grant", 1, "touch")

        ids = set(CreditBucket.objects.filter(user=user, source="subscription").values_list("purchase_id", flat=True))
        assert ids == {purchase.pk}


class TestQueueing:
    def test_a_monthly_plan_bought_during_a_week_starts_when_the_week_ends(self, buy, ledger, user, clock):
        buy(user, "weekly_pro", quantity=1)
        clock.advance(days=3)

        done = buy(user, "monthly_pro")

        (week, month) = periods(user)
        assert month.starts_at == week.ends_at and month.ends_at == week.ends_at + 28 * DAY
        assert (week.status, month.status) == ("active", "queued") and done.periods == [month]
        assert ledger.balance(user) == 100  # the monthly credits are not here yet
        clock.set(week.ends_at)
        ledger.grant(user, "admin_grant", 1, "touch")
        assert ledger.balance(user) == 500 + 1
        sound(user)

    def test_buying_the_same_plan_again_queues_behind_it(self, buy, user, clock):
        buy(user, "monthly_pro")

        buy(user, "monthly_pro")

        first, second = periods(user)
        assert second.starts_at == first.ends_at == clock.now() + 28 * DAY
        assert (first.status, second.status) == ("active", "queued")

    def test_different_plans_never_overlap(self, buy, user):
        buy(user, "weekly_pro", quantity=2)
        buy(user, "pro_plus")
        buy(user, "weekly_pro", quantity=1)

        made = periods(user)
        assert all(a.ends_at == b.starts_at for a, b in zip(made, made[1:], strict=False))
        assert [p.credits for p in made] == [100, 100, 750, 100]

    def test_a_purchase_after_everything_ended_starts_now(self, buy, ledger, user, clock):
        buy(user, "weekly_pro", quantity=1)
        clock.advance(days=40)

        buy(user, "monthly_pro")

        assert periods(user)[-1].starts_at == clock.now()
        assert ledger.balance(user) == 500

    def test_twelve_periods_may_be_open_and_the_thirteenth_is_refused_before_anything_is_made(self, buy, desk, user):
        buy(user, "weekly_pro", quantity=12)
        made_before = (PlanPurchase.objects.count(), PlanPeriod.objects.count())

        with pytest.raises(QueueFull) as refused:
            desk.open(user, "weekly_pro", quantity=1)

        assert refused.value.get_codes() == "queue_full" and refused.value.status_code == 409
        assert (PlanPurchase.objects.count(), PlanPeriod.objects.count()) == made_before

    def test_the_limit_counts_what_is_open_not_what_ended(self, buy, desk, user, clock, ledger):
        buy(user, "weekly_pro", quantity=12)
        clock.advance(days=14)  # two weeks ended
        ledger.grant(user, "admin_grant", 1, "touch")

        desk.open(user, "weekly_pro", quantity=2)  # fits again

        assert PlanPurchase.objects.filter(status="pending").count() == 1

    def test_the_limit_is_a_setting(self, buy, desk, user):
        from credits.models import CreditSettings

        CreditSettings.objects.update_or_create(pk=1, defaults={"max_queued_periods": 2})
        buy(user, "weekly_pro", quantity=2)

        with pytest.raises(QueueFull):
            desk.open(user, "pro_plus")

    def test_one_learners_queue_does_not_count_for_another(self, buy, desk, user, other_user):
        buy(user, "weekly_pro", quantity=12)

        desk.open(other_user, "weekly_pro", quantity=12)


class TestSpendableTheMomentAPeriodStarts:
    def test_without_any_job_the_credits_are_there_when_the_wallet_is_touched(self, ledger, buy, user, clock):
        buy(user, "weekly_pro", quantity=2)
        ledger.debit(user, 100, "x", "spend-week-one")
        clock.advance(days=7)

        placed = ledger.place_hold(user, 60, "lesson.create", "h", subject_id=__import__("uuid").uuid4())

        assert placed.hold.amount == 60 and ledger.balance(user) == 40

    def test_a_period_nobody_used_is_recorded_as_granted_then_expired(self, ledger, buy, user, clock):
        buy(user, "weekly_pro", quantity=1)
        clock.advance(days=8)

        ledger.grant(user, "admin_grant", 1, "touch")

        types = [r.type for r in CreditTransaction.objects.filter(user=user).order_by("id")]
        assert types == ["grant", "expire", "grant"]
        expire = CreditTransaction.objects.get(user=user, type="expire")
        assert expire.amount == -100 and ledger.balance(user) == 1
        assert [p.status for p in periods(user)] == ["ended"]
        sound(user)

    def test_weeks_that_passed_while_nobody_looked_are_each_granted_then_expired_in_order(
        self, ledger, buy, user, clock
    ):
        buy(user, "weekly_pro", quantity=3)
        clock.advance(days=16)

        ledger.grant(user, "admin_grant", 1, "touch")

        types = [(r.type, r.amount) for r in CreditTransaction.objects.filter(user=user).order_by("id")]
        assert types == [  # each week granted when it began, the two that passed expired, the third running
            ("grant", 100),
            ("grant", 100),
            ("grant", 100),
            ("expire", -100),
            ("expire", -100),
            ("grant", 1),
        ]
        assert [p.status for p in periods(user)] == ["ended", "ended", "active"] and ledger.balance(user) == 101
        sound(user)

    def test_a_part_used_period_expires_what_is_left(self, ledger, buy, user, clock):
        buy(user, "weekly_pro", quantity=1)
        ledger.debit(user, 30, "x", "d")
        clock.advance(days=7)

        ledger.grant(user, "admin_grant", 1, "touch")

        assert CreditTransaction.objects.get(user=user, type="expire").amount == -70


class TestFulfilmentIsOnce:
    def test_fulfilling_twice_grants_once(self, desk, fulfilment, ledger, user):
        purchase = desk.open(user, "weekly_pro", quantity=2)

        first = fulfilment.fulfil(purchase)
        again = fulfilment.fulfil(purchase)

        assert first.created and not again.created
        assert PlanPeriod.objects.filter(user=user).count() == 2 and ledger.balance(user) == 100
        sound(user)

    def test_one_time_credits_fulfilled_twice_grant_once(self, desk, fulfilment, ledger, user):
        purchase = desk.open(user, "one_time", credits=100)

        fulfilment.fulfil(purchase)
        fulfilment.fulfil(purchase)

        assert ledger.balance(user) == 100 and CreditBucket.objects.filter(user=user).count() == 1

    def test_a_purchase_that_was_voided_cannot_be_fulfilled(self, desk, fulfilment, user):
        purchase = desk.open(user, "one_time", credits=100)
        PlanPurchase.objects.filter(pk=purchase.pk).update(status="void")
        purchase.refresh_from_db()

        with pytest.raises(ValueError):
            fulfilment.fulfil(purchase)

        assert not CreditBucket.objects.exists()

    def test_the_result_after_the_first_time_describes_the_same_periods(self, desk, fulfilment, user):
        purchase = desk.open(user, "weekly_pro", quantity=2)
        first = fulfilment.fulfil(purchase)

        again = fulfilment.fulfil(purchase)

        assert [p.pk for p in again.periods] == [p.pk for p in first.periods]


class TestWhoDecidesWhat:
    def test_an_unknown_plan_is_refused(self, desk, user):
        with pytest.raises(InvalidPlanRequest) as refused:
            desk.open(user, "platinum")

        assert refused.value.get_codes() == "invalid_plan" and not PlanPurchase.objects.exists()

    def test_a_plan_that_is_switched_off_is_refused(self, desk, user):
        Plan.objects.filter(key="pro_plus").update(active=False)

        with pytest.raises(InvalidPlanRequest) as refused:
            desk.open(user, "pro_plus")

        assert refused.value.get_codes() == "invalid_plan"

    def test_the_amount_comes_from_the_plan_table(self, desk, user):
        Plan.objects.filter(key="monthly_pro").update(price_paise=20900)

        assert desk.open(user, "monthly_pro").amount_paise == 20900

    def test_the_credits_come_from_the_plan_table_when_each_period_starts(self, buy, ledger, user):
        Plan.objects.filter(key="monthly_pro").update(credits=600)

        buy(user, "monthly_pro")

        assert ledger.balance(user) == 600

    def test_an_open_purchase_is_pending_and_grants_nothing(self, desk, ledger, user):
        purchase = desk.open(user, "weekly_pro", quantity=2)

        assert purchase.status == "pending" and purchase.fulfilled_at is None
        assert ledger.balance(user) == 0 and not PlanPeriod.objects.exists()

    def test_opening_a_purchase_with_a_known_id_returns_it(self, desk, user):
        import uuid

        chosen = uuid.uuid4()
        first = desk.open(user, "weekly_pro", quantity=2, purchase_id=chosen)

        again = desk.open(user, "weekly_pro", quantity=2, purchase_id=chosen)

        assert again.pk == first.pk == chosen and PlanPurchase.objects.count() == 1


class TestAdministratorsPurchases:
    def test_it_is_free_marked_and_says_why(self, desk, fulfilment, ledger, user):
        purchase = desk.open(
            user, "monthly_pro", source="admin", by="staff@example.com", reason="Support: apology for the outage"
        )

        assert (purchase.source, purchase.amount_paise) == ("admin", 0)
        assert purchase.meta == {
            "reason": "Support: apology for the outage",
            "by": "staff@example.com",
            "list_amount_paise": 19900,
        }
        fulfilment.fulfil(purchase)
        assert ledger.balance(user) == 500
        sound(user)

    def test_an_administrator_needs_a_reason(self, desk, user):
        with pytest.raises(InvalidPlanRequest):
            desk.open(user, "monthly_pro", source="admin", by="staff@example.com", reason="  ")

        assert not PlanPurchase.objects.exists()

    def test_the_queue_limit_applies_to_gifts_too(self, desk, buy, user):
        buy(user, "weekly_pro", quantity=12)

        with pytest.raises(QueueFull):
            desk.open(user, "weekly_pro", source="admin", by="staff", reason="why")

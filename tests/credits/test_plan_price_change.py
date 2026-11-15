"""Unit under test: the plan prices approved on 2026-11-15 (migration `0009_raise_plan_prices`, `PlanSeed`), as the
checkout, `GET /api/credits/plans` and `GET /api/public/pricing` show them.

Why: prices are money. The approved change doubles one-time credits (₹1 to ₹2 a credit) and raises the subscription
plans to three times their original price (Weekly Pro ₹49 to ₹147, Monthly Pro ₹199 to ₹597, Pro Plus ₹279 to ₹837),
and changes nothing else: the credits a plan gives and the credits an action costs stay as they were, so a lesson is
the same ten credits. What people already paid is history and must not move. A price an admin has edited by hand must
not be overwritten by a migration, and the migration must be undoable.

Use cases:
- the plans as the public pricing endpoint states them: a credit is ₹2 (200 paise), Weekly Pro ₹147 for 100 credits,
  Monthly Pro ₹597 for 500, Pro Plus ₹837 for 750, with the price of one credit worked out from them
- the plans as the signed-in learner's endpoint states them (the same four prices)
- what the rules charge for them: a minimum purchase of 10 one-time credits is ₹20, three weeks of Weekly Pro is ₹441
- credits and periods per plan are unchanged, and a lesson (10 credits) earns ₹20.00 one-time, ₹14.70, ₹11.94 and
  ₹11.16 (the table is in `docs/architecture/credits-system.md`)
- the code's `PlanSeed` and the migration agree on the final prices, and the migration starts from the original ones
- the migration takes a plan still at its original price straight to the final one, leaves one an admin edited alone,
  and touches nothing but the plan rows: a purchase, a period and a bucket already made keep what was paid and given
- undoing the migration puts the original prices back (only on plans still at the final price)
"""

import importlib
from datetime import UTC, datetime

import pytest
from django.apps import apps

from credits.models import CreditBucket, Plan, PlanPeriod, PlanPurchase
from credits.plans.desk import PurchaseDesk
from credits.plans.pricing import PlanPricing
from credits.plans.seed import PlanSeed
from credits.pricing.seed import PriceSeed

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
NEW = {"one_time": 200, "weekly_pro": 14700, "monthly_pro": 59700, "pro_plus": 83700}
OLD = {"one_time": 100, "weekly_pro": 4900, "monthly_pro": 19900, "pro_plus": 27900}
CREDITS = {"one_time": 0, "weekly_pro": 100, "monthly_pro": 500, "pro_plus": 750}
PERIOD_DAYS = {"one_time": 365, "weekly_pro": 7, "monthly_pro": 28, "pro_plus": 28}
LESSON_CREDITS = 10


@pytest.fixture(autouse=True)
def seeded(db):
    PlanSeed().apply()
    PriceSeed().apply()


def migration():
    return importlib.import_module("credits.migrations.0009_raise_plan_prices")


def terms(key: str):
    return PurchaseDesk.terms_of(Plan.objects.get(key=key))


class TestThePricesTheEndpointsShow:
    def test_the_public_pricing_states_the_four_new_prices(self, api_client):
        body = api_client.get("/api/public/pricing").json()

        prices = {p["key"]: p["price_paise"] for p in body["plans"]}
        assert prices == {k: v for k, v in NEW.items() if k != "one_time"}
        assert body["one_time"]["price_paise_per_credit"] == NEW["one_time"]
        assert body["one_time"]["min_credits"] == 10
        assert {p["key"]: p["price_paise_per_credit"] for p in body["plans"]} == {
            "weekly_pro": 147.0,
            "monthly_pro": 119.4,
            "pro_plus": 111.6,
        }

    def test_the_signed_in_plans_endpoint_states_the_same_prices(self, signed_in_client):
        body = signed_in_client.get("/api/credits/plans").json()

        assert {p["key"]: p["price_paise"] for p in body["plans"]} == NEW
        assert body["one_time"]["price_paise_per_credit"] == NEW["one_time"]


class TestWhatTheRulesCharge:
    def test_the_smallest_one_time_purchase_of_ten_credits_is_twenty_rupees(self):
        priced = PlanPricing().price(terms("one_time"), credits=10, minimum=10, maximum=5000)

        assert priced.amount_paise == 2000

    def test_three_weeks_of_weekly_pro_is_four_hundred_forty_one_rupees(self):
        priced = PlanPricing().price(terms("weekly_pro"), quantity=3, minimum=10, maximum=5000)

        assert (priced.amount_paise, priced.periods) == (44100, 3)

    def test_what_each_plan_gives_is_unchanged(self):
        for plan in Plan.objects.all():
            assert (plan.credits, plan.period_days) == (CREDITS[plan.key], PERIOD_DAYS[plan.key]), plan.key

    def test_a_lesson_earns_these_rupees_on_each_plan(self):
        earned = {
            key: round(LESSON_CREDITS * (price if key == "one_time" else price / CREDITS[key]) / 100, 2)
            for key, price in NEW.items()
        }

        assert earned == {"one_time": 20.0, "weekly_pro": 14.7, "monthly_pro": 11.94, "pro_plus": 11.16}


class TestTheSeedAndTheMigrationAgree:
    def test_the_seed_class_holds_the_new_prices(self):
        assert {row[0]: row[4] for row in PlanSeed.PLANS} == NEW

    def test_the_migration_names_the_same_prices(self):
        assert {key: new for key, _old, new in migration().CHANGES} == NEW
        assert {key: old for key, old, _new in migration().CHANGES} == OLD


class TestTheMigration:
    def test_it_takes_a_plan_still_at_its_original_price_straight_to_the_final_one(self):
        Plan.objects.update(price_paise=0)
        for key, price in OLD.items():
            Plan.objects.filter(key=key).update(price_paise=price)

        migration().raise_prices(apps, None)

        assert {p.key: p.price_paise for p in Plan.objects.all()} == NEW

    def test_it_leaves_a_price_an_admin_edited_alone(self):
        for key, price in OLD.items():
            Plan.objects.filter(key=key).update(price_paise=price)
        Plan.objects.filter(key="monthly_pro").update(price_paise=20900)  # edited in the console

        migration().raise_prices(apps, None)

        assert Plan.objects.get(key="monthly_pro").price_paise == 20900
        assert Plan.objects.get(key="weekly_pro").price_paise == NEW["weekly_pro"]

    def test_it_changes_nothing_but_the_plan_prices(self, user):
        weekly = Plan.objects.get(key="weekly_pro")
        Plan.objects.filter(pk=weekly.pk).update(price_paise=OLD["weekly_pro"])
        purchase = PlanPurchase.objects.create(user=user, plan=weekly, quantity=1, amount_paise=4900, created_at=AT)
        bucket = CreditBucket.objects.create(
            user=user, source="subscription", amount_granted=100, amount_remaining=100, expires_at=AT, created_at=AT,
            purchase_id=purchase.pk,
        )  # fmt: skip
        period = PlanPeriod.objects.create(
            user=user, purchase=purchase, position=1, starts_at=AT, ends_at=AT, credits=100, bucket=bucket
        )

        migration().raise_prices(apps, None)

        purchase.refresh_from_db(), period.refresh_from_db(), bucket.refresh_from_db()
        assert purchase.amount_paise == 4900  # what was paid is what was paid
        assert (period.credits, bucket.amount_remaining, bucket.amount_granted) == (100, 100, 100)
        assert Plan.objects.get(pk=weekly.pk).price_paise == NEW["weekly_pro"]
        assert (weekly.credits, weekly.period_days, weekly.max_quantity) == (100, 7, 12)

    def test_undoing_it_puts_the_original_prices_back_on_plans_at_the_final_price(self):
        Plan.objects.filter(key="pro_plus").update(price_paise=84900)  # edited after the change

        migration().lower_prices(apps, None)

        by_key = {p.key: p.price_paise for p in Plan.objects.all()}
        assert by_key["one_time"] == OLD["one_time"] and by_key["weekly_pro"] == OLD["weekly_pro"]
        assert by_key["monthly_pro"] == OLD["monthly_pro"]
        assert by_key["pro_plus"] == 84900

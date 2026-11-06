"""Unit under test: `credits.models` Plan, PlanPurchase and PlanPeriod with their constraints,
`credits.plans.seed.PlanSeed`, and
migrations 0006 (the plan tables) and 0007 (the plans).

Why: plans are what money buys, so the table that says what each costs and gives has to hold the spec's numbers (D1), a
purchase has to say who bought what for how much and where it came from, and a period has to be unique within its
purchase so a
retried fulfilment cannot make two. A learner with purchases cannot be deleted by accident, and the migrations must
add the
tables, seed the plans without overwriting an edit, and come out cleanly.

Use cases:
- the seeded plans are the spec's: one-time credits 100 paise a credit; Weekly Pro 100 credits, 7 days, 4,900 paise,
  up to 12
  weeks; Monthly Pro 500 credits, 28 days, 19,900 paise; Pro Plus 750 credits, 28 days, 27,900 paise
- a plan key is unique; the seed adds only plans that are missing and never overwrites an edit, and can be repeated
- a purchase has a status, a source and a quantity of at least one; a period is unique within its purchase by position
- the buckets of a purchase can be found by its id, and an index backs that
- a learner with a purchase or a period cannot be deleted by accident
- migration 0007 seeds the same plans as `PlanSeed`, never overwrites, and can be undone; 0006 can be undone and
  redone with the
  learners untouched
"""

import importlib
from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import ProtectedError

from credits.models import Plan, PlanPeriod, PlanPurchase
from credits.plans.seed import PlanSeed

AT = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

SPEC = {
    "one_time": dict(credits=0, period_days=365, price_paise=100, max_quantity=1),
    "weekly_pro": dict(credits=100, period_days=7, price_paise=4900, max_quantity=12),
    "monthly_pro": dict(credits=500, period_days=28, price_paise=19900, max_quantity=1),
    "pro_plus": dict(credits=750, period_days=28, price_paise=27900, max_quantity=1),
}


@pytest.mark.django_db
class TestThePlans:
    @pytest.fixture(autouse=True)
    def seeded(self, db):
        PlanSeed().apply()

    def test_the_seeded_plans_are_the_specs(self):
        for key, terms in SPEC.items():
            plan = Plan.objects.get(key=key)
            assert {f: getattr(plan, f) for f in terms} == terms and plan.active is True
        assert [p.key for p in Plan.objects.order_by("sort")] == list(SPEC)

    def test_a_key_is_unique(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            Plan.objects.create(key="weekly_pro", name="Again", credits=1, period_days=1, price_paise=1, sort=9)

    def test_the_seed_adds_only_what_is_missing_and_never_overwrites_an_edit(self):
        Plan.objects.filter(key="monthly_pro").update(price_paise=20900)
        Plan.objects.filter(key="pro_plus").delete()

        added = PlanSeed().apply()

        assert added == 1 and Plan.objects.get(key="monthly_pro").price_paise == 20900
        assert Plan.objects.get(key="pro_plus").credits == 750 and PlanSeed().apply() == 0

    def test_a_switched_off_plan_is_not_brought_back_by_the_seed(self):
        Plan.objects.filter(key="pro_plus").update(active=False)

        PlanSeed().apply()

        assert Plan.objects.get(key="pro_plus").active is False


@pytest.mark.django_db
class TestPurchasesAndPeriods:
    @pytest.fixture(autouse=True)
    def seeded(self, db):
        PlanSeed().apply()

    def purchase(self, user, plan="weekly_pro", **fields):
        return PlanPurchase.objects.create(
            user=user, plan=Plan.objects.get(key=plan), quantity=fields.pop("quantity", 1), amount_paise=4900,
            created_at=AT, **fields,
        )  # fmt: skip

    def test_a_purchase_starts_pending_and_from_a_payment(self, user):
        purchase = self.purchase(user)

        assert (purchase.status, purchase.source, purchase.meta, purchase.fulfilled_at) == (
            "pending",
            "payment",
            {},
            None,
        )

    def test_the_quantity_is_at_least_one(self, user):
        with pytest.raises(IntegrityError), transaction.atomic():
            self.purchase(user, quantity=0)

    def test_a_period_is_unique_within_its_purchase_by_position(self, user):
        purchase = self.purchase(user)
        PlanPeriod.objects.create(user=user, purchase=purchase, position=1, starts_at=AT, ends_at=AT, credits=100)

        with pytest.raises(IntegrityError), transaction.atomic():
            PlanPeriod.objects.create(user=user, purchase=purchase, position=1, starts_at=AT, ends_at=AT, credits=100)

    def test_a_period_starts_queued_with_no_bucket(self, user):
        purchase = self.purchase(user)

        period = PlanPeriod.objects.create(
            user=user, purchase=purchase, position=1, starts_at=AT, ends_at=AT, credits=100
        )

        assert (period.status, period.bucket) == ("queued", None)

    def test_a_learner_with_a_purchase_cannot_be_deleted_by_accident(self, user):
        self.purchase(user)

        with pytest.raises(ProtectedError):
            user.delete()

    def test_a_plan_with_purchases_cannot_be_deleted(self, user):
        purchase = self.purchase(user)

        with pytest.raises(ProtectedError):
            purchase.plan.delete()

    def test_the_buckets_of_a_purchase_are_found_by_an_index(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'credits_creditbucket'")
            definitions = " ".join(row[0] for row in cursor.fetchall())

        assert "purchase_id" in definitions


class TestTheMigrations:
    TABLES = {"credits_plan", "credits_planpurchase", "credits_planperiod"}

    @staticmethod
    def migrate(targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)

    @staticmethod
    def latest():
        # every app's newest: `payments` is undone with `credits` and has to come back with it
        return list(MigrationExecutor(connection).loader.graph.leaf_nodes())

    @pytest.mark.django_db
    def test_0007_seeds_the_plans_the_seed_class_holds(self):
        from django.apps import apps

        Plan.objects.all().delete()
        module = importlib.import_module("credits.migrations.0007_plan_seed")

        module.seed(apps, None)

        assert {p.key: {f: getattr(p, f) for f in SPEC["weekly_pro"]} for p in Plan.objects.all()} == SPEC

    @pytest.mark.django_db
    def test_0007_never_overwrites_and_can_be_undone(self):
        from django.apps import apps

        module = importlib.import_module("credits.migrations.0007_plan_seed")
        Plan.objects.update_or_create(key="monthly_pro", defaults=dict(
            name="Mine", credits=1, period_days=1, price_paise=1, max_quantity=1, sort=3, active=True
        ))  # fmt: skip

        module.seed(apps, None)
        assert Plan.objects.get(key="monthly_pro").name == "Mine"

        Plan.objects.create(key="custom", name="Custom", credits=1, period_days=1, price_paise=1, sort=9)
        module.unseed(apps, None)
        assert list(Plan.objects.values_list("key", flat=True)) == ["custom"]

    @pytest.mark.django_db(transaction=True)
    def test_0006_can_be_undone_and_redone_with_the_learners_untouched(self, user):
        try:
            self.migrate([("credits", "0005_streak_days")])
            assert not self.TABLES & set(connection.introspection.table_names())
            from accounts.models import User

            assert User.objects.filter(pk=user.pk).exists()
        finally:
            self.migrate(self.latest())
        assert self.TABLES <= set(connection.introspection.table_names())

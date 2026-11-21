"""Unit under test: `core.audit.seeder` (`AuditSeeder` and `SeedGuard`): making every persona, safely and repeatably.

Why: the seed makes accounts with a known password. It must refuse to run anywhere that is not a throwaway stack, and
running it again (the audit stack is stopped and started) must change nothing but the passwords: no second plan, no
second grant of credits, no second history.

Use cases:
- the guard refuses outside DEBUG, with Supabase as the database, with no password and with a short one, and its
  messages never hold the password
- seeding makes all ten personas, each with what it should have (no credits, a plan bought, a streak, a history, staff)
- seeding again makes nothing new, applies no step, and buys and builds nothing twice
- the report names personas and addresses and holds no password
- `only` limits the run to some personas, `skip` leaves out a kind of step, and `progress` hears each persona
"""

import pytest

from core.audit.accounts import PersonaAccounts
from core.audit.personas import AuditPersonas, SeedWorld
from core.audit.seeder import AuditSeeder, SeedGuard, SeedRefused
from credits.earning.days import StreakDays
from credits.earning.localday import LocalDay
from credits.earning.zone import LearnerZone
from credits.ledger import Ledger
from credits.models import Plan, PlanPurchase
from credits.plans.seed import PlanSeed
from lessons.models import Lesson, TestSubmission

pytestmark = pytest.mark.django_db

PASSWORD = "audit-test-password-1"


class Shop:
    """The two slow steps, made quick: a plan is a purchase row, a history is a lesson, two attempts and a quiz."""

    def __init__(self, make_quiz):
        self.bought, self.built = [], []
        self.make_quiz = make_quiz

    def buy(self, user, plan_key, quantity=1):
        from django.utils import timezone

        PlanSeed().apply()
        PlanPurchase.objects.create(
            user=user, plan=Plan.objects.get(key=plan_key), quantity=quantity, amount_paise=0, created_at=timezone.now()
        )
        self.bought.append(plan_key)

    def build(self, user):
        lesson = Lesson.objects.create(owner=user, topic="Binary search")
        for number in (1, 2):
            TestSubmission.objects.create(lesson=lesson, attempt_no=number, status="graded", questions=[], answers={})
        self.make_quiz(owner=user)
        self.built.append(user.pk)


@pytest.fixture
def shop(make_quiz):
    return Shop(make_quiz)


@pytest.fixture
def seeder(shop, settings, monkeypatch):
    settings.DEBUG = True
    # The command runs in autocommit, where "after the account is committed" means at once: do the same here, or the
    # signup credits would arrive after the steps that count them.
    monkeypatch.setattr("django.db.transaction.on_commit", lambda func, using=None, robust=False: func())
    monkeypatch.setenv("AUDIT_PERSONA_PASSWORD", PASSWORD)
    ledger = Ledger()
    world = SeedWorld(
        ledger=ledger,
        days=StreakDays(ledger.clock),
        purchases=shop,
        history=shop,
        today=lambda user: LocalDay.today(ledger.clock, LearnerZone.of(user)).date,
    )
    return AuditSeeder(world)


class TestGuard:
    def test_it_refuses_outside_debug(self, settings, monkeypatch):
        settings.DEBUG = False
        monkeypatch.setenv("AUDIT_PERSONA_PASSWORD", PASSWORD)

        with pytest.raises(SeedRefused, match="DJANGO_DEBUG"):
            SeedGuard().password()

    def test_it_refuses_to_write_to_supabase(self, settings, monkeypatch):
        settings.DEBUG = True
        settings.USING_SUPABASE = True
        monkeypatch.setenv("AUDIT_PERSONA_PASSWORD", PASSWORD)

        with pytest.raises(SeedRefused, match="Supabase"):
            SeedGuard().password()

    @pytest.mark.parametrize("given", [None, "short"])
    def test_it_refuses_a_missing_or_short_password_and_never_repeats_it(self, settings, monkeypatch, given):
        settings.DEBUG = True
        settings.USING_SUPABASE = False
        monkeypatch.delenv("AUDIT_PERSONA_PASSWORD", raising=False)
        if given:
            monkeypatch.setenv("AUDIT_PERSONA_PASSWORD", given)

        with pytest.raises(SeedRefused) as refused:
            SeedGuard().password()

        assert "AUDIT_PERSONA_PASSWORD" in str(refused.value) and (given is None or given not in str(refused.value))

    def test_it_gives_the_password_where_it_may_run(self, settings, monkeypatch):
        settings.DEBUG = True
        settings.USING_SUPABASE = False
        monkeypatch.setenv("AUDIT_PERSONA_PASSWORD", PASSWORD)

        assert SeedGuard().password() == PASSWORD


class TestSeeding:
    def test_every_persona_is_made_with_what_it_should_have(self, seeder, shop):
        report = seeder.seed()

        results = {r.persona.slug: r for r in report.results}
        assert len(results) == 10 and all(r.created for r in results.values())
        from accounts.models import User

        def user(slug):
            return User.objects.get(email=f"audit-{slug}@example.test")

        assert Ledger().balance(user("zero-credits")) == 0
        assert sorted(shop.bought) == ["monthly_pro", "pro_plus", "weekly_pro"]
        assert shop.built == [user("history").pk] and user("staff").is_staff
        assert user("hindi").profile.preferred_language == "hi" and not user("google").has_usable_password()
        assert user("new-learner").profile.is_complete is False and Ledger().balance(user("new-learner")) == 30

    def test_seeding_again_makes_nothing_new_and_buys_and_builds_nothing_twice(self, seeder, shop):
        seeder.seed()
        again = seeder.seed()

        assert not any(r.created for r in again.results)
        assert [r.applied for r in again.results if r.applied] == []
        assert len(shop.bought) == 3 and len(shop.built) == 1

    def test_the_report_names_the_personas_and_holds_no_password(self, seeder):
        report = seeder.seed(only={"staff"})

        assert [r.persona.email for r in report.results] == ["audit-staff@example.test"]
        assert PASSWORD not in repr(report)

    def test_only_limits_the_run_skip_leaves_out_a_kind_of_step_and_progress_hears_each_persona(self, seeder, shop):
        heard = []

        report = seeder.seed(only={"history", "zero-credits"}, skip={"HaveHistory"}, progress=heard.append)

        assert [r.persona.slug for r in report.results] == ["zero-credits", "history"]
        assert heard == ["zero-credits", "history"] and shop.built == []

    def test_a_custom_catalogue_is_what_is_seeded(self, seeder):
        only_staff = [p for p in AuditPersonas.all() if p.slug == "staff"]
        small = AuditSeeder(seeder.world, personas=only_staff, accounts=PersonaAccounts())

        assert [r.persona.slug for r in small.seed().results] == ["staff"]

"""Unit under test: `core.audit.personas`: the audit's synthetic learners, and the steps that make each one what it is.

Why: the audit judges the app by what these learners see, so each persona must really have what its name says (no
credits, a plan, a streak that can be repaired, a history), and seeding twice must not pile on more (a second plan, a
second history, credits given again). A persona that is almost right gives the auditors false findings.

Use cases:
- the catalogue holds the ten personas the runbook asks for, with distinct slugs and `audit-<slug>@example.test`
  addresses that the app also sees as ten inboxes (not `+tags`), each with the property its name promises (language,
  sign-in, staff, plan, no profile)
- LeaveCredits takes a balance down to exactly the figure (or tops it up to it) and does nothing when it is already so
- TopUpTo raises a balance to a floor and leaves a bigger one alone
- HoldPlan buys the plan through the purchaser unless the learner already has it
- HaveStreak puts a run of days ending the day before yesterday, so yesterday's miss is repairable, and does it once
- HaveHistory builds a history unless the learner already has a lesson
- a step applied twice does its work once, and says whether it did anything
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.emailrules.canonical import EmailCanonicalizer
from core.audit.personas import (
    AuditPersonas,
    HaveHistory,
    HaveStreak,
    HoldPlan,
    LeaveCredits,
    SeedWorld,
    TopUpTo,
)
from credits.earning.days import StreakDays
from credits.earning.localday import LocalDay
from credits.earning.repair import StreakRepairService
from credits.earning.zone import LearnerZone
from credits.ledger import Ledger
from credits.models import Plan, PlanPurchase
from credits.plans.seed import PlanSeed

pytestmark = pytest.mark.django_db


class Recorder:
    """Stands in for the two slow steps and remembers what it was asked."""

    def __init__(self):
        self.bought, self.built = [], []

    def buy(self, user, plan_key, quantity=1):
        self.bought.append((plan_key, quantity))

    def build(self, user):
        self.built.append(user.pk)


@pytest.fixture
def recorder():
    return Recorder()


@pytest.fixture
def world(recorder):
    ledger = Ledger()
    return SeedWorld(
        ledger=ledger,
        days=StreakDays(ledger.clock),
        purchases=recorder,
        history=recorder,
        today=lambda user: LocalDay.today(ledger.clock, LearnerZone.of(user)).date,
    )


@pytest.fixture
def funded(user, world):
    world.ledger.adjust(user, 30, "test-fund", reason="test", actor="test")
    return user


class TestCatalogue:
    def test_it_holds_the_ten_personas_with_distinct_slugs_and_synthetic_addresses(self):
        personas = AuditPersonas.all()

        assert len(personas) == 10
        assert len({p.slug for p in personas}) == 10
        assert all(p.email == f"audit-{p.slug}@example.test" for p in personas)

    def test_no_two_personas_are_the_same_inbox_to_the_app(self):
        # A `+tag` is dropped when the app decides "have we seen this person" (phase 11, D7): audit+a@ and audit+b@
        # would be one account, and only the first persona could be made.
        canonical = {EmailCanonicalizer.of(p.email) for p in AuditPersonas.all()}

        assert len(canonical) == len(AuditPersonas.all())

    def test_each_persona_has_the_property_its_name_promises(self):
        by_slug = {p.slug: p for p in AuditPersonas.all()}

        assert by_slug["new-learner"].onboarded is False and by_slug["new-learner"].steps == ()
        assert LeaveCredits(0) in by_slug["zero-credits"].steps
        assert [s.plan_key for p in ("weekly", "monthly", "pro-plus") for s in by_slug[p].steps] == [
            "weekly_pro",
            "monthly_pro",
            "pro_plus",
        ]
        assert any(isinstance(s, HaveStreak) for s in by_slug["streak"].steps)
        assert any(isinstance(s, HaveHistory) for s in by_slug["history"].steps)
        assert by_slug["hindi"].language == "hi"
        assert by_slug["google"].sign_in == "google"
        assert by_slug["staff"].staff is True


class TestCredits:
    def test_leave_credits_takes_a_balance_down_to_the_figure_once(self, funded, world):
        step = LeaveCredits(0)

        assert step.apply(funded, world) is True
        assert world.ledger.balance(funded) == 0
        assert step.apply(funded, world) is False

    def test_leave_credits_tops_a_smaller_balance_up_to_the_figure(self, funded, world):
        assert LeaveCredits(100).apply(funded, world) is True

        assert world.ledger.balance(funded) == 100

    def test_top_up_raises_a_balance_to_the_floor_and_leaves_a_bigger_one_alone(self, funded, world):
        assert TopUpTo(300).apply(funded, world) is True
        assert world.ledger.balance(funded) == 300

        assert TopUpTo(200).apply(funded, world) is False
        assert world.ledger.balance(funded) == 300


class TestPlan:
    def test_it_buys_the_plan_through_the_purchaser(self, user, world, recorder):
        assert HoldPlan("weekly_pro", 2).apply(user, world) is True

        assert recorder.bought == [("weekly_pro", 2)]

    def test_it_does_not_buy_a_plan_the_learner_already_has(self, user, world, recorder):
        PlanSeed().apply()
        PlanPurchase.objects.create(
            user=user, plan=Plan.objects.get(key="weekly_pro"), amount_paise=0, created_at=timezone.now()
        )

        assert HoldPlan("weekly_pro").apply(user, world) is False
        assert recorder.bought == []


class TestStreak:
    def test_a_run_ending_the_day_before_yesterday_leaves_yesterday_repairable(self, funded, world):
        assert HaveStreak(5).apply(funded, world) is True

        today = world.today(funded)
        days = world.days.dates(funded)
        assert {today - timedelta(days=n) for n in range(2, 7)} <= days and today - timedelta(days=1) not in days
        outlook = StreakRepairService().outlook(funded)
        assert outlook.available and outlook.day == today - timedelta(days=1)

    def test_it_is_done_once(self, funded, world):
        HaveStreak(3).apply(funded, world)

        assert HaveStreak(3).apply(funded, world) is False
        assert len(world.days.dates(funded)) == 3


class TestHistory:
    def test_it_builds_a_history_unless_the_learner_has_a_lesson(self, user, world, recorder, make_lesson):
        assert HaveHistory().apply(user, world) is True
        assert recorder.built == [user.pk]

        make_lesson()

        assert HaveHistory().apply(user, world) is False
        assert recorder.built == [user.pk]

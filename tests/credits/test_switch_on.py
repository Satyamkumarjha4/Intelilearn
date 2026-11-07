"""Unit under test: the switch-on of credits (phase 10.9): the new defaults of `ACTION_GATE` and `ACTIVITY_SINK`, the
signup backfill that must come first, and what happens to work already running when the gate changes.

Why: until now nobody paid for anything, and the day the default gate becomes `CreditGate` every action is charged.
Three things must be true that day: an account that existed before has its 30 credits already, or the first thing it
tries is refused; the tests that were written when nothing cost anything keep meaning what they meant (the root fixture
pins the open gate and the do-nothing sink, so only a test that asks for credits has them); and a lesson or quiz
that was already being built (it carries no authorization, because the open gate gave none) finishes free instead of
being charged, or "given back", for something nobody ever took.

Use cases:
- the defaults are the credit gate and the credits sink, as the settings module says
- every ordinary test still runs on the open gate and the do-nothing sink, whatever the defaults are
- an account made before credits has nothing and is refused (402) at its first paid action; after `grant_signup_credits`
  it has 30 that never expire and the same action is allowed; running it again changes nothing
- a run started before the switch has no authorization; finishing, stopping or failing it after the switch charges
  nothing, gives nothing back, and writes nothing to the ledger; a Retry of it asks nothing
- work started after the switch is charged as it should be (the other side of the same rule)
"""

import importlib

import pytest
from django.core.management import call_command

from credits.ledger import Ledger
from credits.models import CreditBucket, CreditTransaction
from lessons.effects import RunEffects
from lessons.metering import ActionMetering, AuthorizationSettlement
from lessons.models import GraphRun, Lesson, Stage
from lessons.services import LessonService

pytestmark = pytest.mark.django_db


class Silent:
    def publish(self, run_id, event):
        pass


def effects():
    return RunEffects(settlement=AuthorizationSettlement())


class TestTheDefaults:
    def test_the_gate_is_the_credit_gate_and_the_sink_earns_credits(self):
        module = importlib.import_module("config.settings")

        assert module.ACTION_GATE == "credits.gate.CreditGate"
        assert module.ACTIVITY_SINK == "credits.activity.CreditsActivitySink"

    def test_an_ordinary_test_still_runs_on_the_open_gate_and_the_do_nothing_sink(self, settings):
        assert settings.ACTION_GATE == "lessons.metering.OpenGate"
        assert settings.ACTIVITY_SINK == "lessons.activity.NullActivity"


class TestBackfillComesFirst:
    def test_an_old_account_is_refused_until_it_has_its_30_and_then_is_not(
        self, signed_in_client, credits_on, user, queue, bound_registry
    ):
        refused = signed_in_client.post("/api/lessons", {"topic": "Binary search"}, format="json")
        assert refused.status_code == 402 and refused.json()["code"] == "insufficient_credits"
        assert Lesson.objects.count() == 0

        call_command("grant_signup_credits")

        bucket = CreditBucket.objects.get(user=user)
        assert (bucket.source, bucket.amount_granted, bucket.expires_at) == ("signup", 30, None)
        allowed = signed_in_client.post("/api/lessons", {"topic": "Binary search"}, format="json")
        assert allowed.status_code == 202 and credits_on.balance(user) == 27

    def test_running_it_again_changes_nothing(self, user, credits_on):
        call_command("grant_signup_credits")
        call_command("grant_signup_credits")

        assert CreditBucket.objects.filter(user=user).count() == 1 and credits_on.balance(user) == 30

    def test_the_dry_run_writes_nothing(self, user, credits_on):
        call_command("grant_signup_credits", "--dry-run")

        assert not CreditBucket.objects.exists()


class TestWorkAlreadyRunningFinishesFree:
    @pytest.fixture
    def before_the_switch(self, user, queue, settings, bound_registry):
        """A lesson and its run, made while the gate was still the open one."""
        settings.ACTION_GATE = "lessons.metering.OpenGate"
        lesson, run = LessonService(queue=queue, events=Silent()).create(user, "Binary search")
        assert "authorization" not in run.payload
        return lesson, run

    @pytest.fixture
    def switched(self, credits_on, user, before_the_switch, settings):
        settings.ACTION_GATE = (
            "credits.gate.CreditGate"  # the switch: after the work above was started on the open gate
        )
        credits_on.fund(user, 20)
        return credits_on

    def test_finishing_charges_nothing(self, switched, user, before_the_switch):
        lesson, run = before_the_switch
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC)
        before = CreditTransaction.objects.filter(user=user).count()

        effects().on_finished(run, ended=True)

        assert switched.balance(user) == 20 and switched.holds(user) == []
        assert CreditTransaction.objects.filter(user=user).count() == before

    def test_stopping_or_failing_charges_nothing_and_gives_nothing_back(self, switched, user, before_the_switch):
        lesson, run = before_the_switch
        before = list(CreditTransaction.objects.filter(user=user).values_list("type", "amount"))

        effects().on_stopped(run, "stopped")

        assert switched.balance(user) == 20 and switched.holds(user) == []
        assert list(CreditTransaction.objects.filter(user=user).values_list("type", "amount")) == before

    def test_a_retry_of_it_asks_nothing(self, switched, user, before_the_switch):
        lesson, run = before_the_switch
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.FAILED)

        assert ActionMetering().ask_again(lesson) is None
        assert switched.balance(user) == 20 and switched.holds(user) == []

    def test_work_started_after_the_switch_is_charged(self, switched, user, queue, bound_registry):
        LessonService(queue=queue, events=Silent()).create(user, "Another topic")

        assert switched.balance(user) == 17 and len(switched.holds(user)) == 1

    def test_the_books_still_balance(self, switched, user, before_the_switch):
        from credits.audit import LedgerAudit

        effects().on_stopped(before_the_switch[1], "stopped")

        assert LedgerAudit().check(user).ok and Ledger().balance(user) == 20

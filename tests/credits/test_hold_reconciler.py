"""Unit under test: `credits.reconcile.HoldReconciler` (credits plan T13), the pass that lets go of reserves nothing is
going to settle.

Why: a reserve is normally settled by the run it belongs to. Two things can leave one stuck: a run that ended in failure
or was stopped but whose settlement was lost (a crash, a gate that raised), and a reserve taken for work whose rows
never
got made (a crash between the ask and the run). Credits stuck that way are credits taken for nothing. But a run that is
merely paused (a quiz waiting for the learner, possibly for days) still owes its work, and releasing its reserve would
give the work away; age alone must never release it.

Use cases:
- a reserve whose latest run failed or was cancelled and was never settled is released, the run is marked settled,
  and the
  credits go back where they came from
- a reserve whose run is queued, running or paused is left alone, however old it is
- a reserve whose run succeeded but was never settled is committed
- the latest run decides: a reserve carried to a later run that is paused is kept even if an earlier run failed
- a reserve nothing claims (no run carries it) is released once its orphan deadline has passed, and not before
- a reserve already settled is not touched, and a pass run twice changes nothing
- one reserve that cannot be released does not stop the others, and is reported
- the report says how many were released as failed, as orphans, and left alone
"""

import uuid
from datetime import timedelta

import pytest

from credits.gate import CreditGate
from credits.models import CreditHold
from credits.reconcile import HoldReconciler
from lessons.metering import ActionContext, AuthorizationLedger, CompletionPoints, MeteredAction, RunOutcome
from lessons.models import GraphRun, Stage

pytestmark = pytest.mark.django_db

CREATE = MeteredAction.LESSON_CREATE
CHECK = {"entry": "diagnostic", "intent": "lesson", "origin": "direct", "covers": "diagnostic"}


@pytest.fixture(autouse=True)
def prices(db):
    from credits.pricing.seed import PriceSeed

    PriceSeed().apply()


@pytest.fixture
def gate(ledger):
    return CreditGate(ledger=ledger)


@pytest.fixture
def reconciler(ledger, gate):
    return HoldReconciler(ledger=ledger, gate=gate)


@pytest.fixture
def funded(user, give):
    give(user, 30)
    return user


def reserve_for(gate, user, lesson, run_status, *, settled=None):
    """A reserve for the lesson's creation, and a run that carries it in the state asked for."""
    context = ActionContext(
        user, CREATE, CHECK, lesson.id, f"lesson.create:{lesson.id}", False, CompletionPoints.of(CREATE, CHECK)
    )
    authorization = gate.authorize(context)
    payload = AuthorizationLedger().payload(authorization)
    if settled:
        payload["authorization"]["settled"] = settled
    run = GraphRun.objects.create(
        lesson=lesson, graph=GraphRun.Graph.FLOW, trigger=GraphRun.Trigger.START, status=run_status, payload=payload
    )
    return authorization, run


def status_of(authorization) -> str:
    return CreditHold.objects.get(pk=authorization.id).status


class TestARunThatEnded:
    @pytest.mark.parametrize("status", [GraphRun.Status.FAILED, GraphRun.Status.CANCELLED])
    def test_a_failed_or_stopped_run_whose_reserve_was_never_settled_is_released(
        self, reconciler, gate, funded, make_lesson, ledger, status
    ):
        authorization, run = reserve_for(gate, funded, make_lesson(), status)

        report = reconciler.run()

        assert status_of(authorization) == "released" and ledger.balance(funded) == 30
        run.refresh_from_db()
        assert run.payload["authorization"]["settled"] == ("cancelled" if status == "cancelled" else "failed")
        assert report.released_failed == 1 and report.released_orphans == 0

    def test_a_run_that_succeeded_but_was_never_settled_is_committed(
        self, reconciler, gate, funded, make_lesson, ledger
    ):
        authorization, run = reserve_for(gate, funded, make_lesson(), GraphRun.Status.SUCCEEDED)

        reconciler.run()

        assert status_of(authorization) == "committed" and ledger.balance(funded) == 27
        run.refresh_from_db()
        assert run.payload["authorization"]["settled"] == "succeeded"

    @pytest.mark.parametrize("status", [GraphRun.Status.QUEUED, GraphRun.Status.RUNNING, GraphRun.Status.PAUSED])
    def test_a_run_still_going_or_paused_keeps_its_reserve_however_old(
        self, reconciler, gate, funded, make_lesson, ledger, clock, status
    ):
        authorization, _ = reserve_for(gate, funded, make_lesson(stage=Stage.AWAITING_DIAGNOSTIC), status)
        clock.advance(days=30)

        report = reconciler.run()

        assert status_of(authorization) == "held" and ledger.balance(funded) == 27
        assert report.left_alone == 1 and report.released_failed == 0 and report.released_orphans == 0

    def test_the_latest_run_decides(self, reconciler, gate, funded, make_lesson):
        lesson = make_lesson()
        authorization, first = reserve_for(gate, funded, lesson, GraphRun.Status.FAILED)
        GraphRun.objects.create(  # a Retry that carried the open reserve on, and is paused now
            lesson=lesson, graph=GraphRun.Graph.FLOW, trigger=GraphRun.Trigger.RETRY, status=GraphRun.Status.PAUSED,
            payload=first.payload,
        )  # fmt: skip

        reconciler.run()

        assert status_of(authorization) == "held"

    def test_a_reserve_already_settled_is_not_touched(self, reconciler, gate, funded, make_lesson, ledger):
        authorization, _ = reserve_for(gate, funded, make_lesson(), GraphRun.Status.FAILED)
        gate.settle(authorization, RunOutcome.FAILED)
        rows = ledger.balance(funded)

        report = reconciler.run()

        assert report.released_failed == 0 and ledger.balance(funded) == rows


class TestAnOrphan:
    def orphan(self, gate, user):
        context = ActionContext(
            user, CREATE, CHECK, uuid.uuid4(), "lesson.create:orphan", False, CompletionPoints.of(CREATE, CHECK)
        )
        return gate.authorize(context)

    def test_a_reserve_no_run_carries_is_released_once_its_deadline_has_passed(
        self, reconciler, gate, funded, ledger, clock
    ):
        authorization = self.orphan(gate, funded)
        clock.advance(minutes=31)

        report = reconciler.run()

        assert status_of(authorization) == "released" and ledger.balance(funded) == 30
        assert report.released_orphans == 1 and report.released_failed == 0

    def test_not_before_the_deadline(self, reconciler, gate, funded, ledger, clock):
        authorization = self.orphan(gate, funded)
        clock.advance(minutes=29)

        report = reconciler.run()

        assert status_of(authorization) == "held" and report.left_alone == 1

    def test_the_deadline_is_the_setting_at_the_time_of_the_ask(self, reconciler, gate, funded, clock):
        from credits.models import CreditSettings

        CreditSettings.objects.update_or_create(pk=1, defaults={"orphan_minutes": 5})
        authorization = self.orphan(gate, funded)
        clock.advance(minutes=6)

        reconciler.run()

        assert status_of(authorization) == "released"

    def test_a_reserve_that_has_a_run_is_not_an_orphan_however_old(self, reconciler, gate, funded, make_lesson, clock):
        authorization, _ = reserve_for(gate, funded, make_lesson(), GraphRun.Status.RUNNING)
        clock.advance(days=3)

        reconciler.run()

        assert status_of(authorization) == "held"


class TestThePass:
    def test_run_twice_it_changes_nothing_the_second_time(self, reconciler, gate, funded, make_lesson, ledger, clock):
        reserve_for(gate, funded, make_lesson(), GraphRun.Status.FAILED)
        clock.advance(hours=1)
        reconciler.run()
        rows = ledger.reserved(funded), ledger.balance(funded)

        second = reconciler.run()

        assert (ledger.reserved(funded), ledger.balance(funded)) == rows
        assert (second.released_failed, second.released_orphans) == (0, 0)

    def test_one_that_cannot_be_released_does_not_stop_the_others(self, ledger, gate, funded, make_lesson):
        bad, _ = reserve_for(gate, funded, make_lesson(), GraphRun.Status.FAILED)
        good, _ = reserve_for(gate, funded, make_lesson(), GraphRun.Status.FAILED)

        class Flaky:
            def settle(self, authorization, outcome):
                if authorization.id == bad.id:
                    raise RuntimeError("database went away")
                return gate.settle(authorization, outcome)

        report = HoldReconciler(ledger=ledger, gate=Flaky()).run()

        assert status_of(bad) == "held" and status_of(good) == "released"
        assert report.released_failed == 1 and report.failures == (bad.id,)

    def test_the_orphan_clock_is_the_ledgers(self, reconciler, gate, funded, ledger, clock):
        context = ActionContext(
            funded, CREATE, CHECK, uuid.uuid4(), "lesson.create:x", False, CompletionPoints.of(CREATE, CHECK)
        )
        authorization = gate.authorize(context)

        assert CreditHold.objects.get(pk=authorization.id).orphan_deadline == clock.now() + timedelta(minutes=30)

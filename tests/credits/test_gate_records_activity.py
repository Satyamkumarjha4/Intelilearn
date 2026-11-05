"""Unit under test: `CreditGate.settle`, the place a metered action's success becomes an activity (credits plan T16).

Why: settlement is where the gate learns the work was done. It is also called twice (a redelivered task), after the fact
(the reconciler) and for work that failed. Only the first success may count, once, and it must count for the day the
learner asked, not the day a worker got round to it.

Use cases:
- settling `succeeded` reports one `metered_action` activity for the learner, at the instant the reserve was made
- settling `failed` or `cancelled` reports nothing
- settling twice, or a late success after a release, reports nothing more
- an authorization the gate never made reports nothing
- a sink that raises does not undo the settlement: the credits are still spent
- with the default sink nothing is reported at all
"""

import uuid

import pytest
from support.activity import CountingActivity, RaisingActivity

from credits.gate import CreditGate
from credits.models import CreditHold
from credits.pricing.seed import PriceSeed
from lessons.activity import ActivityKind
from lessons.metering import ActionContext, Authorization, CompletionPoints, MeteredAction, RunOutcome

pytestmark = pytest.mark.django_db

CREATE = MeteredAction.LESSON_CREATE
CHECK = {"entry": "diagnostic", "intent": "lesson", "origin": "direct", "covers": "diagnostic"}


@pytest.fixture(autouse=True)
def prices(db):
    PriceSeed().apply()


@pytest.fixture
def sink():
    return CountingActivity()


@pytest.fixture
def gate(ledger, sink):
    return CreditGate(ledger=ledger, activity=sink)


@pytest.fixture
def funded(user, give):
    give(user, 20)
    return user


def ask(gate, user):
    subject = uuid.uuid4()
    context = ActionContext(
        user, CREATE, CHECK, subject, f"lesson.create:{subject}", False, CompletionPoints.of(CREATE, CHECK)
    )
    return gate.authorize(context)


def test_a_success_reports_one_activity_at_the_instant_the_reserve_was_made(gate, funded, sink, clock):
    authorization = ask(gate, funded)
    asked_at = clock.now()
    clock.advance(hours=5)

    gate.settle(authorization, RunOutcome.SUCCEEDED)

    assert sink.recorded == [(funded, ActivityKind.METERED_ACTION, asked_at)]
    assert CreditHold.objects.get(pk=authorization.id).created_at == asked_at


@pytest.mark.parametrize("outcome", [RunOutcome.FAILED, RunOutcome.CANCELLED])
def test_a_failure_or_a_stop_reports_nothing(gate, funded, sink, outcome):
    gate.settle(ask(gate, funded), outcome)

    assert sink.recorded == []


def test_settling_twice_reports_once(gate, funded, sink):
    authorization = ask(gate, funded)

    gate.settle(authorization, RunOutcome.SUCCEEDED)
    gate.settle(authorization, RunOutcome.SUCCEEDED)

    assert len(sink.recorded) == 1


def test_a_late_success_after_a_release_reports_nothing(gate, funded, sink):
    authorization = ask(gate, funded)
    gate.settle(authorization, RunOutcome.FAILED)

    gate.settle(authorization, RunOutcome.SUCCEEDED)

    assert sink.recorded == []


def test_an_authorization_the_gate_never_made_reports_nothing(gate, funded, sink):
    stranger = Authorization.of(
        ActionContext(funded, CREATE, CHECK, uuid.uuid4(), "k", False, CompletionPoints.of(CREATE, CHECK))
    )

    gate.settle(stranger, RunOutcome.SUCCEEDED)

    assert sink.recorded == []


def test_a_sink_that_raises_does_not_undo_the_settlement(ledger, funded):
    broken = RaisingActivity()
    gate = CreditGate(ledger=ledger, activity=broken)
    authorization = ask(gate, funded)

    gate.settle(authorization, RunOutcome.SUCCEEDED)

    assert len(broken.recorded) == 1
    assert CreditHold.objects.get(pk=authorization.id).status == "committed" and ledger.balance(funded) == 17


def test_with_the_default_sink_nothing_is_reported(ledger, funded):
    gate = CreditGate(ledger=ledger)  # the configured sink is the do-nothing one

    gate.settle(ask(gate, funded), RunOutcome.SUCCEEDED)

    assert ledger.balance(funded) == 17


def test_an_exempt_learners_success_is_reported_too(ledger, user, sink):
    from credits.models import Wallet

    Wallet.objects.create(user=user, credits_exempt=True, created_at=ledger.clock.now())
    gate = CreditGate(ledger=ledger, activity=sink)

    gate.settle(ask(gate, user), RunOutcome.SUCCEEDED)

    assert len(sink.recorded) == 1

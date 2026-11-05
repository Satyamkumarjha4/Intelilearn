"""Unit under test: `credits.gate.CreditGate` (the real `ActionGate`), `ExemptPolicy`, and the refusals
`InsufficientCredits` and `PriceUnavailable`.

Why: the gate is where a learner's credits meet the work that costs model calls. It must take the credits before the
work
exists, give them back if the work does not happen, never charge twice for one ask and never let one ask be free because
an earlier one with the same key was settled. It must also never let a price edited in between change the price of work
that is already under way.

Use cases:
- authorize prices the action, reserves exactly that many credits, and answers with an authorization whose id is the
  reserve's id and whose meta carries the credits and the lines charged; the run it travels with stores it
- an action that costs nothing is still reserved (at 0), so it is recorded
- too few credits refuses with 402 `insufficient_credits`, carrying `required` and `available`, and writes nothing
- a missing price refuses with 503 `price_unavailable` and writes nothing, never charging 0
- the same ask again while it is open (a double click, a retried request) returns the same authorization and takes
  nothing more
- an ask again after the first was settled, with the same key (another sheet on the same lesson), takes a fresh reserve:
  it is a new piece of work; so does a Retry, which asks as a resume
- settle `succeeded` keeps the credits spent; `failed` and `cancelled` give them back, each to where they came from; a
  second settle, a settle the other way, and a settle of an authorization the gate never made are harmless
- the price is fixed when the reserve is taken: an edit afterwards changes neither what is held nor what comes back
- a learner whose wallet is exempt gets a reserve of 0 carrying the lines it would have cost, flagged exempt, and
  needs no
  credits; being staff does not exempt
- an ask that finds another reserve open for the same action and subject is refused with 409 `action_in_progress`
- the gate is the one `ACTION_GATE` names
"""

import uuid

import pytest

from credits.exempt import ExemptPolicy
from credits.gate import CreditGate
from credits.models import CreditHold, CreditTransaction, Wallet
from credits.pricing.book import PriceCatalog
from credits.pricing.seed import PriceSeed
from credits.refusals import ActionInProgress, InsufficientCredits, PriceUnavailable
from lessons.metering import (
    ActionContext,
    ActionGates,
    ActionRefused,
    Authorization,
    CompletionPoints,
    MeteredAction,
    RunOutcome,
)

pytestmark = pytest.mark.django_db

CREATE, CONTINUE, SHEET = MeteredAction.LESSON_CREATE, MeteredAction.LESSON_CONTINUE, MeteredAction.SHEET_GENERATE
CHECK = {"entry": "diagnostic", "intent": "lesson", "origin": "direct", "covers": "diagnostic"}  # costs 3
FREE_SHEET = {
    "choice": "sheets_only",
    "perfect": False,
    "intent": "sheets",
    "sheets": 1,
    "grounding": "quiz",
}  # costs 0


@pytest.fixture(autouse=True)
def prices(db):
    PriceSeed().apply()


@pytest.fixture
def gate(ledger):
    return CreditGate(ledger=ledger)


@pytest.fixture
def funded(user, give):
    give(user, 20)
    return user


def ask(gate, user, action=CREATE, size=None, subject=None, key=None, resume=False):
    subject = subject or uuid.uuid4()
    size = CHECK if size is None else size
    context = ActionContext(
        user, action, dict(size), subject, key or f"{action}:{subject}", resume, CompletionPoints.of(action, size)
    )
    return gate.authorize(context)


def in_order() -> list:
    """The reserves in the order they were made (the clock is stopped, so their times tie)."""
    from django.db.models import Min

    return list(CreditHold.objects.annotate(first=Min("transactions__id")).order_by("first"))


def hold_of(authorization) -> CreditHold:
    return CreditHold.objects.get(pk=authorization.id)


class TestAuthorize:
    def test_it_reserves_the_price_and_answers_with_the_reserves_id_and_the_lines(self, gate, funded, ledger):
        subject = uuid.uuid4()

        authorization = ask(gate, funded, subject=subject)

        hold = hold_of(authorization)
        assert authorization.id == str(hold.pk) and authorization.tracked is True
        assert (hold.amount, hold.status, hold.exempt, hold.subject_id) == (3, "held", False, subject)
        assert (hold.action, hold.subject_kind) == ("lesson.create", "lesson")
        assert authorization.meta == {
            "credits": 3,
            "exempt": False,
            "lines": [{"key": "lesson.check", "label": "Quick check", "credits": 3}],
        }
        assert hold.lines == authorization.meta["lines"]
        assert ledger.balance(funded) == 17 and ledger.reserved(funded) == 3

    def test_the_authorization_is_what_the_context_asked_for(self, gate, funded):
        authorization = ask(gate, funded, size=CHECK, resume=True)

        assert authorization.action == CREATE and authorization.size == CHECK and authorization.resume is True
        assert authorization.completes_at == CompletionPoints.of(CREATE, CHECK)

    def test_it_survives_being_stored_on_a_run_and_read_back(self, gate, funded):
        authorization = ask(gate, funded)

        again = Authorization.from_payload(authorization.to_payload())

        assert again.id == authorization.id and again.meta == authorization.meta

    @pytest.mark.parametrize(
        ("action", "kind"),
        [
            (CREATE, "lesson"),
            (CONTINUE, "lesson"),
            (MeteredAction.LESSON_FOLLOWUP, "lesson"),
            (SHEET, "lesson"),
            (MeteredAction.TEST_RETAKE, "test_attempt"),
            (MeteredAction.QUIZ_CREATE, "quiz"),
            (MeteredAction.QUIZ_RETAKE, "quiz_attempt"),
        ],
    )
    def test_the_reserve_says_what_kind_of_thing_it_is_about(self, gate, funded, action, kind):
        sizes = {
            CREATE: CHECK,
            CONTINUE: {"choice": "lesson"},
            MeteredAction.LESSON_FOLLOWUP: {
                "entry": "followup",
                "intent": "lesson",
                "origin": "followup",
                "covers": "all",
                "followup_level": "foundation",
            },  # fmt: skip
            SHEET: {"sheets": 1, "grounding": "none"},
            MeteredAction.TEST_RETAKE: {"question_count": 10, "attempt_no": 2},
            MeteredAction.QUIZ_CREATE: {
                "num_questions": 5,
                "source_type": "topic",
                "sources": 0,
                "level_mode": "self_rating",
                "has_subjective": False,
            },  # fmt: skip
            MeteredAction.QUIZ_RETAKE: {"num_questions": 5, "source_type": "topic"},
        }

        authorization = ask(gate, funded, action, sizes[action])

        assert hold_of(authorization).subject_kind == kind

    def test_an_action_that_costs_nothing_is_still_reserved(self, gate, funded, ledger):
        authorization = ask(gate, funded, CONTINUE, FREE_SHEET)

        hold = hold_of(authorization)
        assert (hold.amount, hold.status) == (0, "held") and authorization.meta["credits"] == 0
        assert [line["key"] for line in hold.lines] == ["sheets.after_check_single"]
        assert ledger.balance(funded) == 20

    def test_too_few_credits_refuses_with_both_numbers_and_writes_nothing(self, gate, user, give, ledger):
        give(user, 2)
        before = CreditTransaction.objects.count()

        with pytest.raises(InsufficientCredits) as refused:
            ask(gate, user)

        error = refused.value
        assert isinstance(error, ActionRefused) and error.status_code == 402
        assert error.get_codes() == "insufficient_credits" and (error.required, error.available) == (3, 2)
        assert error.extra == {"required": 3, "available": 2}
        assert "3 credits" in str(error.detail) and "2" in str(error.detail)
        assert CreditTransaction.objects.count() == before and not CreditHold.objects.exists()
        assert ledger.balance(user) == 2

    def test_a_learner_with_no_wallet_at_all_is_refused_the_same_way(self, gate, user):
        with pytest.raises(InsufficientCredits) as refused:
            ask(gate, user)

        assert (refused.value.required, refused.value.available) == (3, 0)

    def test_a_missing_price_refuses_with_503_and_writes_nothing(self, gate, funded):
        from credits.models import ActionPrice

        ActionPrice.objects.filter(key="lesson.check").delete()

        with pytest.raises(PriceUnavailable) as refused:
            ask(gate, funded)

        assert refused.value.status_code == 503 and not CreditHold.objects.exists()

    def test_the_same_ask_while_it_is_open_returns_the_same_authorization_and_takes_nothing_more(
        self, gate, funded, ledger
    ):
        subject = uuid.uuid4()
        first = ask(gate, funded, subject=subject)

        again = ask(gate, funded, subject=subject)

        assert again.id == first.id and CreditHold.objects.count() == 1
        assert ledger.balance(funded) == 17

    def test_a_new_ask_after_the_first_was_settled_with_the_same_key_is_new_work_and_takes_a_fresh_reserve(
        self, gate, funded, ledger
    ):
        lesson = uuid.uuid4()
        size = {"sheets": 1, "grounding": "none"}  # 2 credits
        first = ask(gate, funded, SHEET, size, subject=lesson, key=f"sheet.generate:{lesson}")
        gate.settle(first, RunOutcome.SUCCEEDED)

        second = ask(gate, funded, SHEET, size, subject=lesson, key=f"sheet.generate:{lesson}")

        assert second.id != first.id
        assert [h.status for h in in_order()] == ["committed", "held"]
        assert ledger.balance(funded) == 16
        assert len({h.idempotency_key for h in CreditHold.objects.all()}) == 2

    def test_a_new_ask_after_a_release_takes_a_fresh_reserve(self, gate, funded, ledger):
        subject = uuid.uuid4()
        first = ask(gate, funded, subject=subject)
        gate.settle(first, RunOutcome.FAILED)

        second = ask(gate, funded, subject=subject)

        assert second.id != first.id and ledger.balance(funded) == 17

    def test_a_retry_asks_as_a_resume_and_takes_a_fresh_reserve(self, gate, funded, ledger):
        lesson = uuid.uuid4()
        first = ask(gate, funded, subject=lesson)
        gate.settle(first, RunOutcome.CANCELLED)

        retry = ask(gate, funded, subject=lesson, key=f"lesson.create:{lesson}:resume1", resume=True)

        assert retry.id != first.id and retry.resume is True and ledger.balance(funded) == 17
        assert [h.status for h in in_order()] == ["released", "held"]

    def test_another_reserve_open_for_the_same_action_and_subject_is_refused_as_in_progress(self, gate, funded):
        subject = uuid.uuid4()
        ask(gate, funded, subject=subject, key="first-key")

        with pytest.raises(ActionInProgress) as refused:
            ask(gate, funded, subject=subject, key="other-key")

        assert refused.value.status_code == 409 and refused.value.get_codes() == "action_in_progress"
        assert CreditHold.objects.count() == 1


class TestSettle:
    def test_succeeded_keeps_the_credits_spent(self, gate, funded, ledger):
        authorization = ask(gate, funded)

        gate.settle(authorization, RunOutcome.SUCCEEDED)

        assert hold_of(authorization).status == "committed" and ledger.balance(funded) == 17
        assert ledger.reserved(funded) == 0

    @pytest.mark.parametrize("outcome", [RunOutcome.FAILED, RunOutcome.CANCELLED])
    def test_failed_and_cancelled_give_the_credits_back(self, gate, funded, ledger, outcome):
        authorization = ask(gate, funded)

        gate.settle(authorization, outcome)

        assert hold_of(authorization).status == "released" and ledger.balance(funded) == 20

    def test_credits_go_back_to_the_buckets_they_came_from(self, gate, user, give, ledger):
        soon = give(user, 2, days=2).transaction.bucket_allocations[0]["bucket"]
        forever = give(user, 10, source="signup").transaction.bucket_allocations[0]["bucket"]
        authorization = ask(gate, user)  # 3: the 2 that expire first, then 1

        gate.settle(authorization, RunOutcome.FAILED)

        from credits.models import CreditBucket

        assert CreditBucket.objects.get(pk=soon).amount_remaining == 2
        assert CreditBucket.objects.get(pk=forever).amount_remaining == 10

    def test_settling_twice_is_harmless(self, gate, funded, ledger):
        authorization = ask(gate, funded)
        gate.settle(authorization, RunOutcome.SUCCEEDED)
        rows = CreditTransaction.objects.count()

        gate.settle(authorization, RunOutcome.SUCCEEDED)

        assert CreditTransaction.objects.count() == rows

    def test_settling_the_other_way_afterwards_changes_nothing(self, gate, funded, ledger):
        authorization = ask(gate, funded)
        gate.settle(authorization, RunOutcome.FAILED)

        gate.settle(authorization, RunOutcome.SUCCEEDED)  # a late success must not charge a released ask

        assert hold_of(authorization).status == "released" and ledger.balance(funded) == 20

    def test_an_authorization_the_gate_never_made_is_ignored(self, gate, funded):
        stranger = Authorization.of(
            ActionContext(funded, CREATE, CHECK, uuid.uuid4(), "k", False, CompletionPoints.of(CREATE, CHECK))
        )

        gate.settle(stranger, RunOutcome.SUCCEEDED)
        gate.settle(Authorization(**{**stranger.__dict__, "id": "not-a-uuid"}), RunOutcome.FAILED)

        assert not CreditHold.objects.exists()


class TestThePriceIsFixedAtTheHold:
    def test_an_edit_afterwards_changes_neither_the_hold_nor_what_comes_back(self, gate, funded, ledger):
        from datetime import UTC, datetime

        authorization = ask(gate, funded)
        PriceCatalog().revise("lesson.check", 6, by="staff", now=datetime(2026, 11, 6, tzinfo=UTC))

        gate.settle(authorization, RunOutcome.FAILED)

        hold = hold_of(authorization)
        assert hold.amount == 3 and hold.lines[0]["credits"] == 3 and ledger.balance(funded) == 20
        assert ask(gate, funded).meta["credits"] == 6  # the next ask pays the new price

    def test_a_repeat_of_an_open_ask_keeps_its_original_price(self, gate, funded):
        from datetime import UTC, datetime

        subject = uuid.uuid4()
        first = ask(gate, funded, subject=subject)
        PriceCatalog().revise("lesson.check", 6, by="staff", now=datetime(2026, 11, 6, tzinfo=UTC))

        again = ask(gate, funded, subject=subject)

        assert again.id == first.id and again.meta["credits"] == 3


class TestExempt:
    def test_an_exempt_wallet_gets_a_reserve_of_zero_with_the_lines_it_would_have_cost(self, gate, user, ledger):
        Wallet.objects.create(user=user, credits_exempt=True, created_at=ledger.clock.now())

        authorization = ask(gate, user)

        hold = hold_of(authorization)
        assert (hold.amount, hold.exempt, hold.status) == (0, True, "held")
        assert hold.lines == [{"key": "lesson.check", "label": "Quick check", "credits": 3}]
        assert authorization.meta["credits"] == 0 and authorization.meta["exempt"] is True
        assert ledger.balance(user) == 0

    def test_it_is_recorded_on_the_ledger_at_zero(self, gate, user, ledger):
        Wallet.objects.create(user=user, credits_exempt=True, created_at=ledger.clock.now())

        authorization = ask(gate, user)
        gate.settle(authorization, RunOutcome.SUCCEEDED)

        rows = CreditTransaction.objects.filter(user=user).order_by("id")
        assert [(r.type, r.amount) for r in rows] == [("hold", 0), ("commit", 0)]

    def test_being_staff_does_not_exempt(self, gate, user, ledger):
        user.is_staff = True
        user.save()

        with pytest.raises(InsufficientCredits):
            ask(gate, user)

    def test_the_policy_reads_the_wallet_flag_and_makes_no_wallet(self, user, ledger):
        policy = ExemptPolicy()
        assert policy.applies_to(user) is False and not Wallet.objects.filter(user=user).exists()

        Wallet.objects.create(user=user, created_at=ledger.clock.now())
        assert policy.applies_to(user) is False

        Wallet.objects.filter(user=user).update(credits_exempt=True)
        assert policy.applies_to(user) is True

    def test_an_exempt_ask_of_a_missing_price_is_still_unavailable(self, gate, user, ledger):
        from credits.models import ActionPrice

        Wallet.objects.create(user=user, credits_exempt=True, created_at=ledger.clock.now())
        ActionPrice.objects.filter(key="lesson.check").delete()

        with pytest.raises(PriceUnavailable):
            ask(gate, user)


def test_the_gate_is_the_one_the_setting_names(settings):
    settings.ACTION_GATE = "credits.gate.CreditGate"

    assert isinstance(ActionGates.default(), CreditGate)

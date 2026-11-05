"""Unit under test: `credits.ledger.Ledger`, the facade over the wallet, buckets, transactions and holds.

Why: every credit a learner has, spends or is given back passes through it. If a hold did not take its credits at
once, a
second request could spend them; if a release put them back in the wrong place, a learner would lose or gain credits; if
a repeated request were not harmless, a retry would charge twice. The ledger must also stay explainable: each row says
what changed and what the balance was after.

Use cases:
- a wallet exists for a learner from their first movement, and is the same one afterwards
- grant makes a bucket and a ledger row with the running balance and its source (so a history can say where credits
  came from); a repeated key changes nothing and returns the first
  result; a key that belongs to another learner is refused; a non-positive amount or an unknown source is refused
- the balance counts buckets that are live and not revoked; the reserved amount counts holds that are held
- a hold takes its credits out of the buckets at once, earliest expiry first, and records where from on the hold and on
  its row (negative amount); a repeated key returns the same hold and takes nothing; too little credit refuses and
  writes
  nothing; a hold of 0 and an exempt hold are still recorded; a second held hold for one action and subject is refused
  while a new one is allowed once the first is settled
- commit settles a hold with a row of 0 and is repeatable; committing a released hold, or an unknown one, is refused
- release returns each allocation to its source bucket (positive row); it is repeatable; an expired source sends the
  credits to a new refund bucket valid 30 days; a revoked source is not refilled and the forfeit is on the row;
  releasing
  a committed hold is refused
- debit spends at once without a hold, as a debit or a streak repair; it refuses when short
- expire writes one row per lapsed bucket for what was left, none for an empty one, is repeatable, and happens by itself
  before any other movement of that wallet
- adjust grants or revokes by an administrator, always with a reason, and never revokes more than the balance
- claw_back takes only the unspent credits of one purchase, never below zero, reports the shortfall, revokes the buckets
  of the purchase that are left empty (even by spending), and is repeatable
- the clock is the only source of time: every timestamp comes from it
"""

from datetime import timedelta

import pytest

from credits.errors import (
    HoldConflict,
    HoldNotFound,
    HoldNotHeld,
    InsufficientBalance,
    InvalidAmount,
    KeyReused,
)
from credits.models import CreditBucket, CreditHold, CreditSettings, CreditTransaction, Wallet
from credits.planner import BucketAllocation  # noqa: F401  (documents what allocations are made of)

pytestmark = pytest.mark.django_db


def rows(user):
    return list(CreditTransaction.objects.filter(user=user).order_by("id"))


def bucket(id) -> CreditBucket:
    return CreditBucket.objects.get(pk=id)


class TestTheWallet:
    def test_it_is_made_by_the_first_movement_and_is_the_same_afterwards(self, ledger, user, give):
        assert not Wallet.objects.filter(user=user).exists()

        give(user, 5)
        give(user, 5)

        assert Wallet.objects.filter(user=user).count() == 1
        assert Wallet.objects.get(user=user).created_at == ledger.clock.now()
        assert Wallet.objects.get(user=user).credits_exempt is False

    def test_a_read_makes_no_wallet(self, ledger, user):
        assert ledger.balance(user) == 0 and ledger.reserved(user) == 0
        assert not Wallet.objects.filter(user=user).exists()


class TestGrant:
    def test_it_makes_a_bucket_and_a_row_with_the_running_balance(self, ledger, user, clock):
        first = ledger.grant(user, "signup", 30, "g1")
        second = ledger.grant(user, "daily", 1, "g2", expires_at=clock.now() + timedelta(days=90), action="daily")

        assert first.created and (first.transaction.type, first.transaction.amount) == ("grant", 30)
        assert (first.transaction.balance_after, second.transaction.balance_after) == (30, 31)
        made = CreditBucket.objects.get(user=user, source="daily")
        assert (made.amount_granted, made.amount_remaining) == (1, 1)
        assert made.expires_at == clock.now() + timedelta(days=90) and made.created_at == clock.now()
        assert CreditBucket.objects.get(source="signup").expires_at is None
        assert second.transaction.action == "daily" and second.transaction.created_at == clock.now()
        assert second.transaction.bucket_allocations == [{"bucket": str(made.pk), "amount": 1}]

    def test_the_row_remembers_where_the_credits_came_from(self, ledger, user):
        row = ledger.grant(user, "weekly_streak", 10, "g", meta={"streak": 7}).transaction

        assert row.meta == {"source": "weekly_streak", "streak": 7}

    def test_a_purchase_id_is_kept_on_the_bucket(self, ledger, user):
        import uuid

        purchase = uuid.uuid4()

        ledger.grant(user, "purchase", 100, "g", purchase_id=purchase)

        assert CreditBucket.objects.get(user=user).purchase_id == purchase

    def test_a_repeated_key_changes_nothing_and_returns_the_first_result(self, ledger, user):
        first = ledger.grant(user, "daily", 5, "same")

        again = ledger.grant(user, "daily", 5, "same")

        assert not again.created and again.transaction.pk == first.transaction.pk
        assert CreditBucket.objects.filter(user=user).count() == 1 and len(rows(user)) == 1

    def test_a_key_that_belongs_to_another_learner_is_refused(self, ledger, user, other_user):
        ledger.grant(user, "daily", 5, "shared-key")

        with pytest.raises(KeyReused):
            ledger.grant(other_user, "daily", 5, "shared-key")

        assert not CreditBucket.objects.filter(user=other_user).exists()

    @pytest.mark.parametrize("amount", [0, -3, 2.5, "7", None, True])
    def test_an_amount_that_is_not_a_positive_whole_number_is_refused(self, ledger, user, amount):
        with pytest.raises(InvalidAmount):
            ledger.grant(user, "daily", amount, "k")

        assert not CreditBucket.objects.exists() and not CreditTransaction.objects.exists()

    def test_an_unknown_source_is_refused(self, ledger, user):
        with pytest.raises(InvalidAmount):
            ledger.grant(user, "lottery", 5, "k")


class TestBalance:
    def test_it_counts_live_buckets_and_leaves_out_lapsed_and_revoked_ones(self, ledger, user, give, clock):
        give(user, 10)
        give(user, 4, days=2)
        give(user, 6, days=-0, source="subscription")  # expires at this very instant: lapsed
        give(user, 9, source="purchase")
        CreditBucket.objects.filter(source="purchase").update(revoked_at=clock.now())

        assert ledger.balance(user) == 10 + 4

    def test_reserved_counts_the_holds_that_are_still_held(self, ledger, user, give):
        give(user, 20)
        a = ledger.place_hold(user, 5, "lesson.create", "h1", subject_id=__import__("uuid").uuid4())
        b = ledger.place_hold(user, 3, "test.retake", "h2", subject_id=__import__("uuid").uuid4())
        ledger.commit(b.hold.pk)

        assert ledger.reserved(user) == 5 and ledger.balance(user) == 12 and a.hold.status == "held"


class TestHold:
    def subject(self):
        return __import__("uuid").uuid4()

    def test_it_takes_the_credits_at_once_earliest_expiry_first_and_records_where_from(self, ledger, user, give):
        late = give(user, 10, days=30).transaction.bucket_allocations[0]["bucket"]
        soon = give(user, 4, days=2).transaction.bucket_allocations[0]["bucket"]
        never = give(user, 10, source="signup").transaction.bucket_allocations[0]["bucket"]
        subject = self.subject()

        placed = ledger.place_hold(
            user, 6, "lesson.create", "hold-1", subject_kind="lesson", subject_id=subject,
            lines=[{"key": "x", "credits": 6}],
        )  # fmt: skip

        assert placed.movement.created
        assert [(a["bucket"], a["amount"]) for a in placed.hold.allocations] == [(soon, 4), (late, 2)]
        assert (bucket(soon).amount_remaining, bucket(late).amount_remaining, bucket(never).amount_remaining) == (
            0,
            8,
            10,
        )
        tx = placed.movement.transaction
        assert (tx.type, tx.amount, tx.balance_after, tx.action) == ("hold", -6, 18, "lesson.create")
        assert (tx.subject_kind, tx.subject_id, tx.hold_id) == ("lesson", subject, placed.hold.pk)
        assert tx.bucket_allocations == placed.hold.allocations
        hold = placed.hold
        assert (hold.status, hold.amount, hold.exempt, hold.lines) == ("held", 6, False, [{"key": "x", "credits": 6}])
        assert hold.user_id == user.pk and hold.created_at == ledger.clock.now() and hold.settled_at is None
        assert ledger.balance(user) == 18

    def test_the_hold_id_can_be_chosen_so_it_can_be_the_authorizations(self, ledger, user, give):
        import uuid

        give(user, 5)
        chosen = uuid.uuid4()

        placed = ledger.place_hold(user, 1, "quiz.create", "k", subject_id=self.subject(), hold_id=chosen)

        assert placed.hold.pk == chosen

    def test_its_orphan_deadline_comes_from_the_settings(self, ledger, user, give, clock):
        give(user, 5)
        CreditSettings.objects.update_or_create(pk=1, defaults={"orphan_minutes": 45})

        placed = ledger.place_hold(user, 1, "quiz.create", "k", subject_id=self.subject())

        assert placed.hold.orphan_deadline == clock.now() + timedelta(minutes=45)

    def test_a_repeated_key_returns_the_same_hold_and_takes_nothing_more(self, ledger, user, give):
        give(user, 10)
        subject = self.subject()
        first = ledger.place_hold(user, 4, "lesson.create", "same", subject_id=subject)

        again = ledger.place_hold(user, 4, "lesson.create", "same", subject_id=subject)

        assert not again.movement.created and again.hold.pk == first.hold.pk
        assert ledger.balance(user) == 6 and CreditHold.objects.count() == 1 and len(rows(user)) == 2

    def test_too_little_credit_refuses_with_both_numbers_and_writes_nothing(self, ledger, user, give):
        give(user, 3)
        before = len(rows(user))

        with pytest.raises(InsufficientBalance) as short:
            ledger.place_hold(user, 5, "lesson.create", "k", subject_id=self.subject())

        assert (short.value.required, short.value.available) == (5, 3)
        assert len(rows(user)) == before and not CreditHold.objects.exists() and ledger.balance(user) == 3

    def test_a_hold_of_zero_is_recorded_so_the_action_is_still_visible(self, ledger, user):
        placed = ledger.place_hold(user, 0, "test.retake", "free", subject_id=self.subject(), lines=[])

        assert placed.hold.amount == 0 and placed.hold.allocations == [] and placed.hold.status == "held"
        assert (placed.movement.transaction.type, placed.movement.transaction.amount) == ("hold", 0)

    def test_an_exempt_hold_is_zero_credits_with_the_lines_it_would_have_paid(self, ledger, user):
        lines = [{"key": "lesson.create", "credits": 3}]

        placed = ledger.place_hold(user, 0, "lesson.create", "ex", subject_id=self.subject(), lines=lines, exempt=True)

        assert placed.hold.exempt is True and placed.hold.amount == 0 and placed.hold.lines == lines

    def test_an_exempt_hold_that_asks_for_credits_is_a_mistake(self, ledger, user, give):
        give(user, 5)

        with pytest.raises(InvalidAmount):
            ledger.place_hold(user, 2, "lesson.create", "ex", subject_id=self.subject(), exempt=True)

    def test_a_second_held_hold_for_one_action_and_subject_is_refused(self, ledger, user, give):
        give(user, 10)
        subject = self.subject()
        ledger.place_hold(user, 2, "lesson.create", "first", subject_id=subject)

        with pytest.raises(HoldConflict):
            ledger.place_hold(user, 2, "lesson.create", "second", subject_id=subject)

        assert ledger.balance(user) == 8 and CreditHold.objects.count() == 1

    def test_the_same_subject_may_be_held_for_a_different_action(self, ledger, user, give):
        give(user, 10)
        subject = self.subject()

        ledger.place_hold(user, 2, "lesson.create", "a", subject_id=subject)
        ledger.place_hold(user, 2, "lesson.continue", "b", subject_id=subject)

        assert ledger.reserved(user) == 4

    def test_once_the_first_is_settled_a_new_hold_for_the_same_action_and_subject_is_allowed(self, ledger, user, give):
        give(user, 10)
        subject = self.subject()
        first = ledger.place_hold(user, 2, "lesson.create", "first", subject_id=subject)
        ledger.release(first.hold.pk)

        second = ledger.place_hold(user, 2, "lesson.create", "second", subject_id=subject)

        assert second.hold.pk != first.hold.pk and ledger.balance(user) == 8

    @pytest.mark.parametrize("amount", [-1, 1.5, "3", None])
    def test_an_amount_that_is_not_a_whole_number_of_credits_is_refused(self, ledger, user, amount):
        with pytest.raises(InvalidAmount):
            ledger.place_hold(user, amount, "lesson.create", "k", subject_id=self.subject())


class TestCommit:
    def placed(self, ledger, user, give, amount=4):
        give(user, 10)
        return ledger.place_hold(user, amount, "lesson.create", "h", subject_id=__import__("uuid").uuid4())

    def test_it_settles_the_hold_with_a_row_of_zero(self, ledger, user, give, clock):
        hold = self.placed(ledger, user, give).hold
        clock.advance(minutes=5)

        done = ledger.commit(hold.pk)

        hold.refresh_from_db()
        assert (hold.status, hold.settled_at) == ("committed", clock.now())
        tx = done.transaction
        assert (tx.type, tx.amount, tx.balance_after, tx.hold_id, tx.action) == (
            "commit",
            0,
            6,
            hold.pk,
            "lesson.create",
        )
        assert ledger.balance(user) == 6 and ledger.reserved(user) == 0

    def test_a_repeat_changes_nothing(self, ledger, user, give):
        hold = self.placed(ledger, user, give).hold
        first = ledger.commit(hold.pk)

        again = ledger.commit(hold.pk)

        assert not again.created and again.transaction.pk == first.transaction.pk and len(rows(user)) == 3

    def test_a_released_hold_cannot_be_committed(self, ledger, user, give):
        hold = self.placed(ledger, user, give).hold
        ledger.release(hold.pk)

        with pytest.raises(HoldNotHeld):
            ledger.commit(hold.pk)

    def test_an_unknown_hold_is_refused(self, ledger):
        with pytest.raises(HoldNotFound):
            ledger.commit(__import__("uuid").uuid4())


class TestRelease:
    def two_buckets(self, ledger, user, give):
        soon = give(user, 4, days=2).transaction.bucket_allocations[0]["bucket"]
        later = give(user, 10, days=20).transaction.bucket_allocations[0]["bucket"]
        hold = ledger.place_hold(user, 6, "lesson.create", "h", subject_id=__import__("uuid").uuid4()).hold
        return hold, soon, later

    def test_each_allocation_goes_back_to_its_source_bucket(self, ledger, user, give, clock):
        hold, soon, later = self.two_buckets(ledger, user, give)
        clock.advance(minutes=3)

        done = ledger.release(hold.pk)

        hold.refresh_from_db()
        assert (bucket(soon).amount_remaining, bucket(later).amount_remaining) == (4, 10)
        assert (hold.status, hold.settled_at) == ("released", clock.now())
        tx = done.transaction
        assert (tx.type, tx.amount, tx.balance_after, tx.hold_id) == ("release", 6, 14, hold.pk)
        assert [(a["bucket"], a["amount"], a["outcome"]) for a in tx.bucket_allocations] == [
            (soon, 4, "returned"),
            (later, 2, "returned"),
        ]
        assert tx.meta["forfeited"] == 0 and ledger.balance(user) == 14

    def test_a_repeat_changes_nothing(self, ledger, user, give):
        hold, *_ = self.two_buckets(ledger, user, give)
        first = ledger.release(hold.pk)

        again = ledger.release(hold.pk)

        assert not again.created and again.transaction.pk == first.transaction.pk
        assert ledger.balance(user) == 14 and len(rows(user)) == 4

    def test_a_committed_hold_cannot_be_released(self, ledger, user, give):
        hold, *_ = self.two_buckets(ledger, user, give)
        ledger.commit(hold.pk)

        with pytest.raises(HoldNotHeld):
            ledger.release(hold.pk)

    def test_a_source_that_has_expired_sends_its_credits_to_a_refund_bucket_valid_30_days(
        self, ledger, user, give, clock
    ):
        hold, soon, later = self.two_buckets(ledger, user, give)
        clock.advance(days=3)  # `soon` has lapsed while the work was going on

        done = ledger.release(hold.pk)

        assert bucket(soon).amount_remaining == 0  # never revived
        refund = CreditBucket.objects.get(user=user, source="refund")
        assert (refund.amount_granted, refund.amount_remaining) == (4, 4)
        assert refund.expires_at == clock.now() + timedelta(days=30) and refund.created_at == clock.now()
        assert bucket(later).amount_remaining == 10
        outcomes = {a["bucket"]: a["outcome"] for a in done.transaction.bucket_allocations}
        assert outcomes == {soon: "refund_bucket", later: "returned"}
        assert done.transaction.amount == 6 and ledger.balance(user) == 14
        assert done.transaction.meta["refund_bucket"] == str(refund.pk)

    def test_the_refund_period_is_a_setting(self, ledger, user, give, clock):
        CreditSettings.objects.update_or_create(pk=1, defaults={"refund_valid_days": 7})
        hold, *_ = self.two_buckets(ledger, user, give)
        clock.advance(days=3)

        ledger.release(hold.pk)

        assert CreditBucket.objects.get(source="refund").expires_at == clock.now() + timedelta(days=7)

    def test_a_revoked_source_is_not_refilled_and_the_forfeit_is_on_the_row(self, ledger, user, give, clock):
        hold, soon, later = self.two_buckets(ledger, user, give)
        CreditBucket.objects.filter(pk=soon).update(revoked_at=clock.now())

        done = ledger.release(hold.pk)

        assert bucket(soon).amount_remaining == 0
        assert not CreditBucket.objects.filter(source="refund").exists()
        tx = done.transaction
        assert (tx.amount, tx.balance_after, tx.meta["forfeited"]) == (2, 10, 4)
        assert {a["bucket"]: a["outcome"] for a in tx.bucket_allocations} == {soon: "forfeited", later: "returned"}

    def test_a_hold_of_zero_releases_to_a_row_of_zero(self, ledger, user):
        hold = ledger.place_hold(user, 0, "test.retake", "z", subject_id=__import__("uuid").uuid4()).hold

        done = ledger.release(hold.pk)

        assert done.transaction.amount == 0 and done.transaction.balance_after == 0

    def test_an_unknown_hold_is_refused(self, ledger):
        with pytest.raises(HoldNotFound):
            ledger.release(__import__("uuid").uuid4())


class TestDebit:
    def test_it_spends_at_once_without_a_hold(self, ledger, user, give):
        give(user, 10)

        done = ledger.debit(user, 1, "streak_repair", "d1", type="repair")

        assert (done.transaction.type, done.transaction.amount, done.transaction.balance_after) == ("repair", -1, 9)
        assert ledger.balance(user) == 9 and not CreditHold.objects.exists()

    def test_it_is_a_plain_debit_by_default_and_repeatable(self, ledger, user, give):
        give(user, 10)
        first = ledger.debit(user, 2, "something", "d")

        again = ledger.debit(user, 2, "something", "d")

        assert first.transaction.type == "debit" and not again.created and ledger.balance(user) == 8

    def test_it_refuses_when_short(self, ledger, user, give):
        give(user, 1)

        with pytest.raises(InsufficientBalance):
            ledger.debit(user, 2, "streak_repair", "d", type="repair")

        assert ledger.balance(user) == 1 and len(rows(user)) == 1

    def test_a_type_that_is_not_a_spend_is_refused(self, ledger, user, give):
        give(user, 5)

        with pytest.raises(InvalidAmount):
            ledger.debit(user, 1, "x", "d", type="grant")


class TestExpiry:
    def test_a_lapsed_bucket_gets_an_expire_row_for_what_was_left(self, ledger, user, give, clock):
        old = give(user, 5, days=2)
        give(user, 7, days=20)
        clock.advance(days=3)

        done = ledger.expire_due(user)

        (moved,) = done
        tx = moved.transaction
        assert (tx.type, tx.amount, tx.balance_after) == ("expire", -5, 7)
        assert tx.bucket_allocations == [{"bucket": old.transaction.bucket_allocations[0]["bucket"], "amount": 5}]
        assert tx.created_at == clock.now() and ledger.balance(user) == 7
        assert CreditBucket.objects.get(source="daily", amount_granted=5).amount_remaining == 0

    def test_an_empty_lapsed_bucket_needs_no_row(self, ledger, user, give, clock):
        give(user, 3, days=1)
        ledger.debit(user, 3, "x", "d")
        clock.advance(days=2)

        assert ledger.expire_due(user) == [] and len(rows(user)) == 2

    def test_a_second_pass_changes_nothing(self, ledger, user, give, clock):
        give(user, 5, days=1)
        clock.advance(days=2)
        ledger.expire_due(user)

        assert ledger.expire_due(user) == [] and len(rows(user)) == 2

    def test_a_bucket_expires_at_its_instant_not_a_moment_before(self, ledger, user, give, clock):
        give(user, 5, days=1)
        clock.advance(days=1, seconds=-1)
        assert ledger.expire_due(user) == []

        clock.advance(seconds=1)

        assert len(ledger.expire_due(user)) == 1

    def test_any_other_movement_expires_what_has_lapsed_first(self, ledger, user, give, clock):
        give(user, 5, days=1)
        give(user, 8, source="signup")
        clock.advance(days=2)

        placed = ledger.place_hold(user, 2, "quiz.create", "k", subject_id=__import__("uuid").uuid4())

        types = [r.type for r in rows(user)]
        assert types == ["grant", "grant", "expire", "hold"]
        assert placed.movement.transaction.balance_after == 6  # 8 − 2, the lapsed 5 already gone

    def test_a_bucket_with_no_expiry_never_lapses(self, ledger, user, give, clock):
        give(user, 5, source="signup")
        clock.advance(days=3650)

        assert ledger.expire_due(user) == [] and ledger.balance(user) == 5


class TestAdjust:
    def test_a_grant_makes_an_admin_bucket_that_never_expires_and_keeps_the_reason_and_actor(self, ledger, user):
        done = ledger.adjust(user, 25, "adj-1", reason="Goodwill after an outage", actor="staff@example.com")

        tx = done.transaction
        assert (tx.type, tx.amount, tx.balance_after) == ("admin_adjust", 25, 25)
        assert tx.meta == {"reason": "Goodwill after an outage", "actor": "staff@example.com"}
        made = CreditBucket.objects.get(user=user)
        assert (made.source, made.amount_granted, made.expires_at) == ("admin_grant", 25, None)

    def test_a_revoke_takes_credits_in_spend_order(self, ledger, user, give):
        give(user, 5, days=3)
        give(user, 5, source="signup")

        done = ledger.adjust(user, -7, "adj-2", reason="Granted twice by mistake", actor="staff@example.com")

        assert (done.transaction.type, done.transaction.amount, done.transaction.balance_after) == (
            "admin_adjust",
            -7,
            3,
        )
        assert ledger.balance(user) == 3 and CreditBucket.objects.get(source="daily").amount_remaining == 0

    @pytest.mark.parametrize("reason", ["", "   ", None])
    def test_a_reason_is_required_and_nothing_is_written_without_one(self, ledger, user, reason):
        with pytest.raises(InvalidAmount):
            ledger.adjust(user, 5, "adj", reason=reason, actor="staff")

        assert not CreditTransaction.objects.exists() and not CreditBucket.objects.exists()

    def test_an_adjustment_of_zero_is_refused(self, ledger, user):
        with pytest.raises(InvalidAmount):
            ledger.adjust(user, 0, "adj", reason="why", actor="staff")

    def test_it_never_revokes_more_than_the_balance(self, ledger, user, give):
        give(user, 3)

        with pytest.raises(InsufficientBalance):
            ledger.adjust(user, -4, "adj", reason="why", actor="staff")

        assert ledger.balance(user) == 3

    def test_a_repeated_key_changes_nothing(self, ledger, user):
        ledger.adjust(user, 5, "adj", reason="why", actor="staff")

        again = ledger.adjust(user, 5, "adj", reason="why", actor="staff")

        assert not again.created and ledger.balance(user) == 5


class TestClawBack:
    def bought(self, ledger, user, give, credits=100, purchase=None):
        import uuid

        purchase = purchase or uuid.uuid4()
        give(user, credits, source="purchase", days=300, purchase_id=purchase)
        return purchase

    def test_it_takes_the_unspent_credits_of_the_purchase_and_nothing_else(self, ledger, user, give):
        purchase = self.bought(ledger, user, give, 100)
        give(user, 20, source="signup")
        ledger.debit(user, 30, "x", "spend")  # earliest expiry first: 30 of the purchase

        done = ledger.claw_back(user, purchase, 50, "refund-1")

        assert (done.taken, done.shortfall) == (50, 0)
        tx = done.movement.transaction
        assert (tx.type, tx.amount, tx.action) == ("refund", -50, "payment_refund")
        assert tx.meta == {"purchase": str(purchase), "requested": 50, "shortfall": 0}
        assert CreditBucket.objects.get(source="purchase").amount_remaining == 20
        assert CreditBucket.objects.get(source="signup").amount_remaining == 20

    def test_it_never_goes_below_zero_and_reports_the_shortfall(self, ledger, user, give):
        purchase = self.bought(ledger, user, give, 100)
        ledger.debit(user, 70, "x", "spend")

        done = ledger.claw_back(user, purchase, 100, "refund-1")

        assert (done.taken, done.shortfall) == (30, 70)
        assert done.movement.transaction.amount == -30 and done.movement.transaction.meta["shortfall"] == 70
        assert ledger.balance(user) == 0

    def test_a_bucket_it_emptied_is_revoked_and_one_it_only_dented_is_not(self, ledger, user, give, clock):
        purchase = self.bought(ledger, user, give, 100)

        ledger.claw_back(user, purchase, 40, "partial")
        assert CreditBucket.objects.get(source="purchase").revoked_at is None

        ledger.claw_back(user, purchase, 60, "rest")

        assert CreditBucket.objects.get(source="purchase").revoked_at == clock.now()

    def test_a_late_release_does_not_refill_a_revoked_bucket(self, ledger, user, give):
        import uuid

        purchase = self.bought(ledger, user, give, 100)
        hold = ledger.place_hold(user, 40, "lesson.create", "h", subject_id=uuid.uuid4()).hold

        refunded = ledger.claw_back(user, purchase, 100, "refund")
        released = ledger.release(hold.pk)

        assert (refunded.taken, refunded.shortfall) == (60, 40)
        assert released.transaction.amount == 0 and released.transaction.meta["forfeited"] == 40
        assert ledger.balance(user) == 0

    def test_a_purchase_that_is_all_in_holds_is_revoked_too_so_a_release_cannot_bring_it_back(self, ledger, user, give):
        import uuid

        purchase = self.bought(ledger, user, give, 100)
        hold = ledger.place_hold(user, 100, "lesson.create", "h", subject_id=uuid.uuid4()).hold

        refunded = ledger.claw_back(user, purchase, 100, "refund")
        released = ledger.release(hold.pk)

        assert (refunded.taken, refunded.shortfall) == (0, 100)
        assert CreditBucket.objects.get(source="purchase").revoked_at is not None
        assert released.transaction.amount == 0 and released.transaction.meta["forfeited"] == 100
        assert ledger.balance(user) == 0

    def test_credits_of_another_purchase_are_not_touched(self, ledger, user, give):
        mine = self.bought(ledger, user, give, 50)
        self.bought(ledger, user, give, 50)

        done = ledger.claw_back(user, mine, 80, "refund")

        assert (done.taken, done.shortfall) == (50, 30) and ledger.balance(user) == 50

    def test_a_purchase_with_no_credits_left_records_the_whole_request_as_shortfall(self, ledger, user):
        import uuid

        done = ledger.claw_back(user, uuid.uuid4(), 10, "refund")

        assert (done.taken, done.shortfall) == (0, 10)
        assert (done.movement.transaction.amount, done.movement.transaction.meta["shortfall"]) == (0, 10)

    def test_a_repeated_key_changes_nothing(self, ledger, user, give):
        purchase = self.bought(ledger, user, give, 100)
        first = ledger.claw_back(user, purchase, 30, "refund")

        again = ledger.claw_back(user, purchase, 30, "refund")

        assert (again.taken, again.shortfall) == (30, 0) and not again.movement.created
        assert again.movement.transaction.pk == first.movement.transaction.pk and ledger.balance(user) == 70

    @pytest.mark.parametrize("credits", [0, -5, 1.5])
    def test_the_request_must_be_a_positive_whole_number(self, ledger, user, credits):
        import uuid

        with pytest.raises(InvalidAmount):
            ledger.claw_back(user, uuid.uuid4(), credits, "refund")


class TestTime:
    def test_every_timestamp_is_the_clocks(self, ledger, user, give, clock):
        import uuid

        give(user, 10)
        clock.advance(hours=7)
        hold = ledger.place_hold(user, 3, "lesson.create", "h", subject_id=uuid.uuid4()).hold
        clock.advance(hours=2)
        ledger.commit(hold.pk)

        stamps = [r.created_at for r in rows(user)]
        start = clock.now() - timedelta(hours=9)
        assert stamps == [start, start + timedelta(hours=7), start + timedelta(hours=9)]
        assert Wallet.objects.get(user=user).created_at == start

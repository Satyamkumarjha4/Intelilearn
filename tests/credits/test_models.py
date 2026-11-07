"""Unit under test: `credits.models`: Wallet, CreditBucket, CreditHold, CreditTransaction and CreditSettings, with their
constraints.

Why: the database is the last line of defence for the ledger. A bucket that could hold more than it was granted, two
holds
for one piece of work, a reused idempotency key, or a ledger row that could be edited would each let a bug turn into
money.
These tests make the constraints and the append-only guard fail loudly instead of trusting the code above them.

Use cases:
- a wallet belongs to one learner, is keyed by them, and has no default timestamp (the clock gives it)
- a bucket must have been granted something and may never hold more than it was granted; the constraint is the
  database's
- only one hold can be held for an action and a subject; a settled one frees the pair; a hold with no subject is never
  in conflict; a hold's idempotency key is unique
- a ledger row's idempotency key is unique; a row cannot be saved again, deleted, or changed or deleted through a
  queryset
- the ledger and its holds refer to a lesson by a plain id, so deleting the lesson leaves the money records alone (K2)
- a learner who has a wallet cannot be deleted by accident
- the credit settings are a singleton with the spec's amounts; the smallest purchase may not exceed the largest
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from credits.errors import AppendOnly
from credits.models import CreditBucket, CreditHold, CreditSettings, CreditTransaction, Wallet

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def bucket(user, granted=10, remaining=10, **fields):
    return CreditBucket.objects.create(
        user=user, source="daily", amount_granted=granted, amount_remaining=remaining, created_at=AT, **fields
    )


def hold(user, key, action="lesson.create", subject=None, status="held"):
    return CreditHold.objects.create(
        user=user, action=action, subject_id=subject, amount=1, status=status, idempotency_key=key, created_at=AT
    )


def row(user, key="k", **fields):
    return CreditTransaction.objects.create(
        user=user, type="grant", amount=1, balance_after=1, idempotency_key=key, created_at=AT, **fields
    )


class TestWallet:
    def test_it_is_keyed_by_its_learner(self, user):
        wallet = Wallet.objects.create(user=user, created_at=AT)

        assert wallet.pk == user.pk and user.wallet == wallet and str(wallet) == f"Wallet of {user}"

    def test_a_learner_has_one_wallet(self, user):
        Wallet.objects.create(user=user, created_at=AT)

        with pytest.raises(IntegrityError), transaction.atomic():
            Wallet.objects.create(user=user, created_at=AT)

    def test_it_takes_its_time_from_the_caller_not_from_the_system(self, user):
        with pytest.raises(IntegrityError), transaction.atomic():
            Wallet.objects.create(user=user)


class TestBucket:
    def test_it_may_hold_up_to_what_was_granted(self, user):
        assert bucket(user, 10, 10).amount_remaining == 10 and bucket(user, 10, 0).amount_remaining == 0

    def test_it_may_not_hold_more_than_it_was_granted(self, user):
        with pytest.raises(IntegrityError), transaction.atomic():
            bucket(user, 10, 11)

    def test_it_must_have_been_granted_something(self, user):
        with pytest.raises(IntegrityError), transaction.atomic():
            bucket(user, 0, 0)

    def test_it_cannot_go_below_zero(self, user):
        with pytest.raises(IntegrityError), transaction.atomic():
            bucket(user, 10, -1)


class TestHold:
    def test_only_one_hold_can_be_held_for_an_action_and_subject(self, user):
        subject = uuid4()
        hold(user, "a", subject=subject)

        with pytest.raises(IntegrityError), transaction.atomic():
            hold(user, "b", subject=subject)

    def test_a_settled_hold_frees_the_pair_and_another_action_is_not_in_conflict(self, user):
        subject = uuid4()
        hold(user, "a", subject=subject, status="released")
        hold(user, "b", subject=subject, status="committed")

        hold(user, "c", subject=subject)
        hold(user, "d", subject=subject, action="lesson.continue")

        assert CreditHold.objects.filter(subject_id=subject).count() == 4

    def test_holds_with_no_subject_never_conflict(self, user):
        hold(user, "a")
        hold(user, "b")

        assert CreditHold.objects.count() == 2

    def test_its_idempotency_key_is_unique(self, user):
        hold(user, "same", subject=uuid4())

        with pytest.raises(IntegrityError), transaction.atomic():
            hold(user, "same", subject=uuid4())


class TestTransaction:
    def test_its_idempotency_key_is_unique(self, user):
        row(user, "once")

        with pytest.raises(IntegrityError), transaction.atomic():
            row(user, "once")

    def test_a_row_that_exists_cannot_be_saved_again(self, user):
        made = row(user)
        made.amount = 99

        with pytest.raises(AppendOnly):
            made.save()

        assert CreditTransaction.objects.get(pk=made.pk).amount == 1

    def test_a_row_cannot_be_deleted(self, user):
        made = row(user)

        with pytest.raises(AppendOnly):
            made.delete()

        assert CreditTransaction.objects.filter(pk=made.pk).exists()

    def test_a_queryset_cannot_update_or_delete_rows(self, user):
        row(user)

        with pytest.raises(AppendOnly):
            CreditTransaction.objects.all().update(amount=5)
        with pytest.raises(AppendOnly):
            CreditTransaction.objects.all().delete()
        with pytest.raises(AppendOnly):
            CreditTransaction.objects.bulk_update([], ["amount"])
        assert CreditTransaction.objects.get().amount == 1

    def test_rows_can_be_added_one_at_a_time_or_together(self, user):
        row(user, "one")
        CreditTransaction.objects.bulk_create(
            [
                CreditTransaction(
                    user=user, type="grant", amount=1, balance_after=2, idempotency_key="two", created_at=AT
                )
            ]
        )

        assert CreditTransaction.objects.count() == 2

    def test_the_newest_row_comes_first(self, user):
        row(user, "one")
        row(user, "two")

        assert [r.idempotency_key for r in CreditTransaction.objects.all()] == ["two", "one"]


class TestPlainReferences:
    def test_deleting_a_lesson_leaves_the_money_records_alone(self, user, lesson):
        row(user, subject_kind="lesson", subject_id=lesson.pk)
        hold(user, "h", subject=lesson.pk)

        lesson.delete()

        assert CreditTransaction.objects.count() == 1 and CreditHold.objects.get().subject_id is not None

    def test_a_learner_with_a_wallet_cannot_be_deleted_by_accident(self, user):
        Wallet.objects.create(user=user, created_at=AT)
        row(user)

        with pytest.raises(ProtectedError):
            user.delete()


class TestSettings:
    def test_they_are_a_singleton_with_the_specs_amounts(self):
        first = CreditSettings.load()
        again = CreditSettings.load()
        again.save()

        assert first.pk == again.pk == 1 and CreditSettings.objects.count() == 1
        assert (first.signup_credits, first.daily_credits, first.weekly_streak_bonus, first.monthly_streak_bonus) == (
            30,
            1,
            10,
            10,
        )
        assert (first.bonus_valid_days, first.purchased_valid_days, first.refund_valid_days) == (90, 365, 30)
        assert (first.repair_cost, first.repair_window_hours, first.repair_limit_week, first.repair_limit_month) == (
            1,
            48,
            1,
            3,
        )
        assert (first.min_one_time_credits, first.max_one_time_credits) == (10, 5000)
        assert not hasattr(first, "paise_per_credit")  # the plan table prices one-time credits, not a setting
        assert (first.max_queued_periods, first.orphan_minutes) == (12, 30)

    def test_a_second_instance_overwrites_the_one_row(self):
        CreditSettings.load()

        CreditSettings(signup_credits=99).save()

        assert CreditSettings.objects.count() == 1 and CreditSettings.load().signup_credits == 99

    def test_the_smallest_purchase_may_not_exceed_the_largest(self):
        from django.core.exceptions import ValidationError

        settings = CreditSettings(min_one_time_credits=500, max_one_time_credits=100)

        with pytest.raises(ValidationError) as bad:
            settings.clean()

        assert "min_one_time_credits" in bad.value.message_dict

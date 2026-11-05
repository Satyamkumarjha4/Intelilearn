"""Unit under test: `credits.models.StreakDay` and `StreakState`, with their constraints (credits plan §7.2).

Why: a streak is counted from its days, so a duplicate day, or a repaired day with no record of when it was repaired
(which the
repair limits count by), would silently change what a learner earns. The database is the last line of defence.

Use cases:
- a learner has at most one row for a date, and the same date for two learners is fine
- a repaired day must say when it was repaired, and an ordinary day must not
- the cached streak is one row for a learner
- a learner with streak days cannot be deleted by accident
"""

from datetime import UTC, date, datetime

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from credits.models import StreakDay, StreakState

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
DAY = date(2026, 11, 5)


def day(user, local_date=DAY, **fields):
    fields.setdefault("kind", "active")
    return StreakDay.objects.create(user=user, local_date=local_date, created_at=AT, **fields)


def test_one_row_for_a_date_and_the_same_date_for_another_learner_is_fine(user, other_user):
    day(user)
    day(other_user)

    with pytest.raises(IntegrityError), transaction.atomic():
        day(user)

    assert StreakDay.objects.count() == 2


def test_a_repaired_day_must_say_when_it_was_repaired(user):
    day(user, kind="repaired", repaired_on=date(2026, 11, 6))

    with pytest.raises(IntegrityError), transaction.atomic():
        day(user, date(2026, 11, 7), kind="repaired")


def test_an_ordinary_day_has_no_repair_date(user):
    with pytest.raises(IntegrityError), transaction.atomic():
        day(user, repaired_on=date(2026, 11, 6))


def test_the_cached_streak_is_one_row_for_a_learner(user):
    StreakState.objects.create(user=user, updated_at=AT)

    with pytest.raises(IntegrityError), transaction.atomic():
        StreakState.objects.create(user=user, updated_at=AT)


def test_a_learner_with_streak_days_cannot_be_deleted_by_accident(user):
    day(user)

    with pytest.raises(ProtectedError):
        user.delete()

"""Unit under test: `lessons.submissions_cleanup.SubmissionDeduplicator`, the data step of the migration that lets a
lesson have only one test submission.

Why: the unique constraint cannot be added while a lesson has several submissions (the test used to be retakeable), and
dev data must not be lost carelessly: the learner's graded result is the one worth keeping. A step that kept the wrong
row would silently swap a learner's score.

Use cases:
- a lesson with one submission loses nothing
- of several submissions the most recent graded one is kept, even when a later one is still grading or failed
- with none graded, the most recent one is kept
- every lesson is judged on its own, and the count of deleted rows is reported
- `plan` reports how many rows would go without deleting them
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from lessons.models import Lesson, TestSubmission
from lessons.submissions_cleanup import SubmissionDeduplicator

pytestmark = pytest.mark.django_db

NOW = timezone.now()


@pytest.fixture(autouse=True)
def old_schema():
    """The table as it was before the migration: without the constraint, so a lesson can have several rows. The DDL
    is rolled back with the test's transaction."""
    constraint = next(c for c in TestSubmission._meta.constraints if c.name == "unique_test_submission_per_lesson")
    with connection.schema_editor() as editor:
        editor.remove_constraint(TestSubmission, constraint)


def submit(lesson, status, minutes):
    submission = TestSubmission.objects.create(lesson=lesson, status=status)
    TestSubmission.objects.filter(pk=submission.pk).update(submitted_at=NOW + timedelta(minutes=minutes))
    return submission


def kept(lesson):
    return list(TestSubmission.objects.filter(lesson=lesson).values_list("pk", flat=True))


def test_a_lesson_with_one_submission_loses_nothing(lesson):
    only = submit(lesson, "failed", 0)

    assert SubmissionDeduplicator().run(TestSubmission) == 0 and kept(lesson) == [only.pk]


def test_the_most_recent_graded_one_is_kept_even_when_a_later_one_is_not_graded(lesson):
    submit(lesson, "graded", 1)
    best = submit(lesson, "graded", 2)
    submit(lesson, "failed", 3)
    submit(lesson, "grading", 4)

    assert SubmissionDeduplicator().run(TestSubmission) == 3 and kept(lesson) == [best.pk]


def test_with_none_graded_the_most_recent_one_is_kept(lesson):
    submit(lesson, "failed", 1)
    latest = submit(lesson, "grading", 2)

    assert SubmissionDeduplicator().run(TestSubmission) == 1 and kept(lesson) == [latest.pk]


def test_every_lesson_is_judged_on_its_own(lesson, make_lesson):
    other = make_lesson()
    mine = submit(lesson, "graded", 1)
    submit(lesson, "failed", 2)
    theirs = submit(other, "failed", 1)

    assert SubmissionDeduplicator().run(TestSubmission) == 1
    assert kept(lesson) == [mine.pk] and kept(other) == [theirs.pk] and Lesson.objects.count() == 2


def test_plan_counts_the_rows_that_would_go_without_deleting_them(lesson):
    submit(lesson, "graded", 1)
    submit(lesson, "graded", 2)
    submit(lesson, "failed", 3)

    assert SubmissionDeduplicator().plan(TestSubmission) == 2
    assert TestSubmission.objects.count() == 3

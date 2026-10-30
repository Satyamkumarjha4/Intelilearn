"""A lesson can have many attempts: the one-submission constraint goes.

It is the last migration of phase 9.2, in the release that ships the retest screens, because until then the code assumed
a lesson had at most one submission. Undoing it is lossy: the constraint can only come back if each lesson has one
attempt, so going back keeps the first attempt of each lesson and deletes the rest (the retakes, and any attempt that is
still open).
"""

from django.db import migrations


def keep_the_first_attempt(apps, schema_editor):
    Submission = apps.get_model("lessons", "TestSubmission")
    for lesson_id in Submission.objects.filter(attempt_no__gt=1).values_list("lesson_id", flat=True).distinct():
        first = Submission.objects.filter(lesson_id=lesson_id).order_by("attempt_no").first()
        Submission.objects.filter(lesson_id=lesson_id).exclude(pk=first.pk).delete()
    Submission.objects.filter(status__in=["generating", "in_progress"]).delete()


class Migration(migrations.Migration):
    dependencies = [("lessons", "0009_graphrun_retake_choices")]

    # Going back runs these in reverse order: the attempts are trimmed first, then the constraint comes back.
    operations = [
        migrations.RemoveConstraint(model_name="testsubmission", name="unique_test_submission_per_lesson"),
        migrations.RunPython(migrations.RunPython.noop, keep_the_first_attempt),
    ]

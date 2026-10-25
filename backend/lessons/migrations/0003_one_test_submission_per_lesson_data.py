from django.db import migrations

from lessons.submissions_cleanup import SubmissionDeduplicator


def keep_one_submission_per_lesson(apps, schema_editor):
    SubmissionDeduplicator().run(apps.get_model("lessons", "TestSubmission"))


class Migration(migrations.Migration):
    """Before the constraint of 0004: the test used to be retakeable, so a lesson may have several submissions."""

    dependencies = [
        ("lessons", "0002_test_submissions"),
    ]

    operations = [
        migrations.RunPython(keep_one_submission_per_lesson, migrations.RunPython.noop),
    ]

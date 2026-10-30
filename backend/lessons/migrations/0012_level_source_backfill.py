"""Every lesson made before self-rating found its level by the quick check, so say so.

Reversible: going back blanks the column (migration 0011 drops it anyway). Only a lesson that has a level is touched.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model("lessons", "Lesson").objects.filter(level_source="").exclude(level="").update(
        level_source="diagnostic"
    )


def backwards(apps, schema_editor):
    apps.get_model("lessons", "Lesson").objects.filter(level_source="diagnostic").update(level_source="")


class Migration(migrations.Migration):
    dependencies = [("lessons", "0011_lesson_entry_columns")]

    operations = [migrations.RunPython(forwards, backwards)]

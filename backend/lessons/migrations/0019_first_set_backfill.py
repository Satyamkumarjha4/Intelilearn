"""Every lesson's test becomes its first set on the record of questions, so `Lesson.final_test` can be dropped (0020).

Reversible: going back writes `final_test` from the first set (the column is back by then, empty).
"""

from django.db import migrations

from lessons.first_sets import FirstSetBackfill


def forwards(apps, schema_editor):
    FirstSetBackfill().forward(apps, schema_editor.connection.alias)


def backwards(apps, schema_editor):
    FirstSetBackfill().backward(apps, schema_editor.connection.alias)


class Migration(migrations.Migration):
    dependencies = [("lessons", "0018_question_first_set")]
    operations = [migrations.RunPython(forwards, backwards)]

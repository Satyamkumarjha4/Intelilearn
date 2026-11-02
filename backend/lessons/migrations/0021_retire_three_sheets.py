"""The old three-sheet mastery choice is retired (phase 9.8): `Lesson.mastery_options` only told a lesson waiting at the
choice which cards to show, and there is one version of the choice now.

The migration refuses to run while any lesson still waits at the old choice: its thread would resume into a path that
no longer exists. Those lessons must be moved on first (open each and choose, with the previous release). Reversible:
the column comes back with the old default on every row.
"""

from django.db import migrations


def refuse_while_anyone_waits(apps, schema_editor):
    Lesson = apps.get_model("lessons", "Lesson")
    waiting = Lesson.objects.using(schema_editor.connection.alias).filter(
        stage="awaiting_choice", mastery_options="three_sheets"
    )
    count = waiting.count()
    if count:
        ids = ", ".join(str(pk) for pk in waiting.values_list("pk", flat=True)[:10])
        noun = "lesson is" if count == 1 else "lessons are"
        raise RuntimeError(
            f"{count} {noun} still waiting at the old three-sheet choice ({ids}). Let each learner choose with the "
            "previous release, then migrate again."
        )


class Migration(migrations.Migration):
    dependencies = [("lessons", "0020_contract_final_test")]
    operations = [
        migrations.RunPython(refuse_while_anyone_waits, migrations.RunPython.noop),
        migrations.RemoveField(model_name="lesson", name="mastery_options"),
    ]

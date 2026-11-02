from django.db import migrations

from lessons.renames import StoredRenames


def to_new_names(apps, schema_editor):
    StoredRenames().forward(apps, schema_editor.connection.alias)


def to_old_names(apps, schema_editor):
    StoredRenames().backward(apps, schema_editor.connection.alias)


class Migration(migrations.Migration):
    """Levels (novice … advanced → beginner … expert, documents stamped `level_scheme: 2`) and difficulties
    (medium → standard, hard → difficult) in every stored lesson. Undoing it is lossy for basic and expert."""

    dependencies = [
        ("lessons", "0005_graphrun_node_timings"),
    ]

    operations = [
        migrations.RunPython(to_new_names, to_old_names),
    ]

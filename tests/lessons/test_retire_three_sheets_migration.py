"""Unit under test: lessons migration 0021 (`retire_three_sheets`), which drops `Lesson.mastery_options` once no lesson
waits at the old three-sheet choice.

Why: that column only told a lesson waiting at the choice which cards to show. With the old cards gone, a lesson that
is still waiting at them would be stranded: its thread resumes into a path that no longer exists. So the migration
refuses to run while any lesson waits there, and says how many and what to do, instead of silently stranding them. A
lesson that is not waiting is unaffected (every lesson created before the Expert lesson has the old value on its
row, and it only matters while the lesson waits).

Use cases:
- with no lesson waiting at the old choice, the column is dropped and every lesson keeps its other data
- a lesson that is waiting at the old choice stops the migration, which names how many there are and leaves the column
- a lesson waiting at the new choice, and a ready lesson that still carries the old value, do not stop it
- undoing it brings the column back, every row with the old default
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("lessons", "0020_contract_final_test")]
AFTER = [("lessons", "0021_retire_three_sheets")]

# One-time data migration: skipped by the everyday local run; CI and `make check-full` run it (docs/process/testing.md).
pytestmark = [pytest.mark.migration, pytest.mark.django_db(transaction=True)]


def latest():
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes())


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def columns() -> set[str]:
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, "lessons_lesson")}


@pytest.fixture
def before(django_user_model):
    apps = migrate(BEFORE)
    owner = django_user_model.objects.create_user("three@example.com", password="x", name="T")
    yield apps, owner
    migrate(latest())  # leave the database at the latest state, whatever migration has been added since


def make(apps, owner, **fields):
    return apps.get_model("lessons", "Lesson").objects.create(owner_id=owner.pk, topic="T", **fields)


def test_with_nobody_waiting_the_column_is_dropped_and_the_rest_is_kept(before):
    apps, owner = before
    lesson = make(apps, owner, stage="ready", route="lesson", mastery_options="three_sheets")

    new = migrate(AFTER)

    assert "mastery_options" not in columns()
    stored = new.get_model("lessons", "Lesson").objects.get(pk=lesson.pk)
    assert (stored.stage, stored.route) == ("ready", "lesson")


def test_a_lesson_waiting_at_the_old_choice_stops_it_and_the_column_stays(before):
    apps, owner = before
    make(apps, owner, stage="awaiting_choice", route="mastery", mastery_options="three_sheets")
    make(apps, owner, stage="awaiting_choice", route="mastery", mastery_options="three_sheets")

    with pytest.raises(RuntimeError, match="2 lessons are still waiting at the old three-sheet choice"):
        migrate(AFTER)

    assert "mastery_options" in columns()
    apps.get_model("lessons", "Lesson").objects.all().delete()  # so the database can go on to the latest state


def test_a_lesson_waiting_at_the_new_choice_does_not_stop_it(before):
    apps, owner = before
    make(apps, owner, stage="awaiting_choice", route="mastery", mastery_options="lesson_or_sheets")

    migrate(AFTER)

    assert "mastery_options" not in columns()


def test_undoing_it_brings_the_column_back_with_the_old_default(before):
    apps, owner = before
    lesson = make(apps, owner, stage="ready", mastery_options="lesson_or_sheets")
    migrate(AFTER)

    old = migrate(BEFORE)

    assert "mastery_options" in columns()
    assert old.get_model("lessons", "Lesson").objects.get(pk=lesson.pk).mastery_options == "three_sheets"

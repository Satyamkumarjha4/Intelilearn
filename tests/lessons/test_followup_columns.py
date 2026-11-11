"""Unit under test: the follow-up link on `Lesson` (`created_from_lesson`, `followup_level`), its constraints, and
lessons migration 0014.

Why: a follow-up is a lesson of its own that remembers which lesson it came from and what kind it is. "Never create a
second Foundation lesson" must hold even when two requests race, so the database enforces it, not just the service;
and a
lesson that outlives its parent must keep working, so deleting the parent must neither delete nor break the follow-up.

Use cases:
- a lesson has no parent and no follow-up level to begin with, and a parent lists its follow-ups
- a follow-up needs a level; a lesson with a level and no parent (its parent was deleted) is fine
- a lesson cannot be its own parent
- a parent can have one Foundation and one Advanced follow-up, and not two of the same level, in the database
- two follow-ups of different parents, and lessons with no parent, can share a level
- deleting the parent keeps the follow-up, clears its link and keeps its level; deleting a follow-up leaves the parent
- an unknown level is refused by validation
- migration 0014 adds the columns to existing lessons (no parent, no level) and can be undone
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from lessons.models import Lesson

BEFORE = [("lessons", "0013_lesson_mastery_options")]
AFTER = [("lessons", "0014_lesson_followup_link")]


def latest():
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes("lessons"))


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db
class TestColumns:
    def test_a_lesson_has_no_parent_and_no_level_and_a_parent_lists_its_followups(self, lesson, make_lesson):
        assert (lesson.created_from_lesson, lesson.followup_level) == (None, "")
        child = make_lesson(
            topic="Foundations of Binary search", created_from_lesson=lesson, followup_level="foundation"
        )

        assert list(lesson.followups.all()) == [child]

    def test_a_followup_needs_a_level(self, lesson, make_lesson):
        with pytest.raises(IntegrityError), transaction.atomic():
            make_lesson(created_from_lesson=lesson, followup_level="")

    def test_a_lesson_with_a_level_and_no_parent_is_fine(self, make_lesson):
        orphan = make_lesson(followup_level="advanced")

        assert Lesson.objects.get(pk=orphan.pk).created_from_lesson is None

    def test_a_lesson_cannot_be_its_own_parent(self, lesson):
        with pytest.raises(IntegrityError), transaction.atomic():
            Lesson.objects.filter(pk=lesson.pk).update(created_from_lesson=lesson, followup_level="foundation")

    def test_a_parent_can_have_one_followup_of_each_level(self, lesson, make_lesson):
        make_lesson(created_from_lesson=lesson, followup_level="foundation")
        make_lesson(created_from_lesson=lesson, followup_level="advanced")

        assert lesson.followups.count() == 2

    @pytest.mark.parametrize("level", ["foundation", "advanced"])
    def test_not_two_followups_of_the_same_level(self, lesson, make_lesson, level):
        make_lesson(created_from_lesson=lesson, followup_level=level)

        with pytest.raises(IntegrityError), transaction.atomic():
            make_lesson(created_from_lesson=lesson, followup_level=level)

    def test_different_parents_and_orphans_can_share_a_level(self, lesson, make_lesson):
        other = make_lesson(topic="Other")
        make_lesson(created_from_lesson=lesson, followup_level="foundation")
        make_lesson(created_from_lesson=other, followup_level="foundation")
        make_lesson(followup_level="foundation")
        make_lesson(followup_level="foundation")

        assert Lesson.objects.filter(followup_level="foundation").count() == 4

    def test_deleting_the_parent_keeps_the_followup_clears_the_link_and_keeps_its_level(self, lesson, make_lesson):
        child = make_lesson(created_from_lesson=lesson, followup_level="foundation")

        lesson.delete()

        child.refresh_from_db()
        assert (child.created_from_lesson, child.followup_level) == (None, "foundation")

    def test_deleting_a_followup_leaves_the_parent_and_frees_the_level(self, lesson, make_lesson):
        child = make_lesson(created_from_lesson=lesson, followup_level="foundation")

        child.delete()

        assert Lesson.objects.filter(pk=lesson.pk).exists()
        make_lesson(created_from_lesson=lesson, followup_level="foundation")  # a new one can be made

    def test_an_unknown_level_is_refused_by_validation(self, lesson, make_lesson):
        child = make_lesson(created_from_lesson=lesson, followup_level="foundation")
        child.followup_level = "intermediate"

        with pytest.raises(ValidationError):
            child.full_clean()


@pytest.mark.migration
@pytest.mark.django_db(transaction=True)
class TestMigration:
    def teardown_method(self):
        migrate(latest())

    def test_existing_lessons_get_no_parent_and_no_level_and_it_can_be_undone(self, django_user_model):
        old = migrate(BEFORE)
        owner = django_user_model.objects.create_user("fu@example.com", password="x", name="F")
        pk = old.get_model("lessons", "Lesson").objects.create(owner_id=owner.pk, topic="T", stage="ready").pk

        new = migrate(AFTER)
        row = new.get_model("lessons", "Lesson").objects.get(pk=pk)
        assert (row.created_from_lesson_id, row.followup_level) == (None, "")

        migrate(BEFORE)
        with connection.cursor() as cursor:
            columns = {c.name for c in connection.introspection.get_table_description(cursor, "lessons_lesson")}
        assert "created_from_lesson_id" not in columns and "followup_level" not in columns

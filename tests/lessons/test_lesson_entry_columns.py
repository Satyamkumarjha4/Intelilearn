"""Unit under test: the columns that say how a lesson came about (`Lesson.intent`, `origin`, `recommended_from`,
`entry`, `level_source`, `self_rating_halves`), their check constraint, and lessons migrations 0011 and 0012.

Why: a self-rated lesson has no quiz behind its level, so the lesson must remember where the level came from and what
the learner rated themselves; the server, not the client, decides a lesson's origin. A rating outside 1 to 10 halves
would make no level, so the database refuses it. The migrations touch real lessons, so every existing lesson must come
out as a direct, quick-check lesson with its level credited to the quick check, and the change must be undoable.

Use cases:
- a new lesson is a direct, quick-check lesson that asks for a lesson, with no rating, no recommendation and no level
  source
- a self-rated lesson keeps its rating, entry and level source
- a rating of 1 to 10 halves is stored and anything else is refused by the database; no rating is allowed
- a recommended lesson keeps the attempt and topic it came from
- a lesson remembers which mastery choice it was shown: the three sheets it was offered before the Expert lesson
  existed (the default, so a lesson already waiting keeps its cards), or the Expert lesson or two sheets once the new
  choice is published; migration 0013 gives every existing lesson the old one
- migration 0012 credits the quick check as the level source of every existing lesson that has a level, leaves a lesson
  without a level alone, and can be undone
- migration 0011 gives every existing lesson the defaults and can be undone
- a stage can move from preparing the quick check straight to building the lesson (self-rating), and from the mastery
  choice to building the lesson (the Expert lesson), but not from the choice back to the quick check
"""

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from graph.nodes.mastery import PublishMasteryOptionsNode
from lessons.models import Lesson, Stage, StageTransitions

BEFORE = [("lessons", "0010_many_attempts_per_lesson")]
COLUMNS = [("lessons", "0011_lesson_entry_columns")]
OPTIONS = [("lessons", "0013_lesson_mastery_options")]
BACKFILLED = [("lessons", "0012_level_source_backfill")]


def latest():
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes("lessons"))


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db
class TestColumns:
    def test_a_new_lesson_is_a_direct_quick_check_lesson_for_a_lesson(self, lesson):
        fresh = Lesson.objects.get(pk=lesson.pk)

        assert (fresh.entry, fresh.intent, fresh.origin) == ("diagnostic", "lesson", "direct")
        assert fresh.self_rating_halves is None and fresh.recommended_from is None and fresh.level_source == ""

    def test_a_self_rated_lesson_keeps_its_rating_entry_and_level_source(self, lesson):
        Lesson.objects.filter(pk=lesson.pk).update(
            entry="self_rating", self_rating_halves=7, level_source="self_rating"
        )

        fresh = Lesson.objects.get(pk=lesson.pk)

        assert (fresh.entry, fresh.self_rating_halves, fresh.level_source) == ("self_rating", 7, "self_rating")

    @pytest.mark.parametrize("halves", [1, 5, 10, None])
    def test_a_rating_of_one_to_ten_halves_or_none_is_stored(self, lesson, halves):
        Lesson.objects.filter(pk=lesson.pk).update(self_rating_halves=halves)

        assert Lesson.objects.get(pk=lesson.pk).self_rating_halves == halves

    @pytest.mark.parametrize("halves", [0, 11, 255])
    def test_a_rating_outside_one_to_ten_halves_is_refused_by_the_database(self, lesson, halves):
        with pytest.raises(IntegrityError), transaction.atomic():
            Lesson.objects.filter(pk=lesson.pk).update(self_rating_halves=halves)

    def test_a_recommended_lesson_keeps_the_attempt_and_topic_it_came_from(self, lesson):
        source = {"attempt_id": "a1", "topic": "Recursion"}
        Lesson.objects.filter(pk=lesson.pk).update(origin="recommendation", recommended_from=source)

        fresh = Lesson.objects.get(pk=lesson.pk)

        assert fresh.origin == "recommendation" and fresh.recommended_from == source


@pytest.mark.django_db
class TestMasteryOptions:
    def test_a_lesson_defaults_to_the_choice_it_was_offered_before_the_expert_lesson(self, lesson):
        assert Lesson.objects.get(pk=lesson.pk).mastery_options == "three_sheets"

    def test_publishing_the_choice_records_the_new_options(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC, route="mastery")

        PublishMasteryOptionsNode()(lesson_state, runtime)

        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, stored.mastery_options) == (Stage.AWAITING_CHOICE, "lesson_or_sheets")

    def test_the_api_says_which_choice_the_lesson_was_shown(self, signed_in_client, lesson):
        before = signed_in_client.get(f"/api/lessons/{lesson.id}").json()["mastery_options"]
        Lesson.objects.filter(pk=lesson.pk).update(mastery_options="lesson_or_sheets")

        after = signed_in_client.get(f"/api/lessons/{lesson.id}").json()["mastery_options"]

        assert (before, after) == ("three_sheets", "lesson_or_sheets")


class TestTransitions:
    @pytest.mark.parametrize(("source", "target"), [
        (Stage.PREPARING_DIAGNOSTIC, Stage.GENERATING_LESSON),
        (Stage.AWAITING_CHOICE, Stage.GENERATING_LESSON),
        (Stage.AWAITING_CHOICE, Stage.GENERATING_MATERIAL),
    ])  # fmt: skip
    def test_the_new_moves_are_allowed(self, source, target):
        assert StageTransitions().allowed(source, target)

    @pytest.mark.parametrize(("source", "target"), [
        (Stage.AWAITING_CHOICE, Stage.PREPARING_DIAGNOSTIC),
        (Stage.AWAITING_CHOICE, Stage.AWAITING_DIAGNOSTIC),
        (Stage.PREPARING_DIAGNOSTIC, Stage.READY),
        (Stage.READY, Stage.GENERATING_LESSON),
    ])  # fmt: skip
    def test_a_move_back_to_the_quiz_or_out_of_ready_is_still_refused(self, source, target):
        assert not StageTransitions().allowed(source, target)


@pytest.mark.django_db(transaction=True)
class TestMigrations:
    def teardown_method(self):
        migrate(latest())

    def make(self, apps, owner_id, **fields):
        fields = {"stage": "ready"} | fields
        return apps.get_model("lessons", "Lesson").objects.create(owner_id=owner_id, topic="T", **fields)

    def test_existing_lessons_get_the_defaults_and_the_quick_check_as_their_level_source(self, django_user_model):
        old = migrate(BEFORE)
        owner = django_user_model.objects.create_user("e@example.com", password="x", name="E")
        leveled = self.make(old, owner.pk, level="foundation").pk
        blank = self.make(old, owner.pk).pk

        new = migrate(BACKFILLED)
        Lesson_ = new.get_model("lessons", "Lesson")

        for pk in (leveled, blank):
            lesson = Lesson_.objects.get(pk=pk)
            assert (lesson.entry, lesson.intent, lesson.origin) == ("diagnostic", "lesson", "direct")
            assert lesson.self_rating_halves is None and lesson.recommended_from is None
        assert Lesson_.objects.get(pk=leveled).level_source == "diagnostic"
        assert Lesson_.objects.get(pk=blank).level_source == ""

    def test_the_backfill_leaves_a_level_source_that_is_already_set_alone(self, django_user_model):
        migrate(COLUMNS)
        new = migrate(COLUMNS)
        owner = django_user_model.objects.create_user("f@example.com", password="x", name="F")
        pk = self.make(new, owner.pk, level="expert", level_source="self_rating").pk

        after = migrate(BACKFILLED)

        assert after.get_model("lessons", "Lesson").objects.get(pk=pk).level_source == "self_rating"

    def test_an_existing_lesson_keeps_the_three_sheet_choice(self, django_user_model):
        old = migrate(BACKFILLED)
        owner = django_user_model.objects.create_user("h@example.com", password="x", name="H")
        pk = self.make(old, owner.pk, stage="awaiting_choice").pk

        new = migrate(OPTIONS)

        assert new.get_model("lessons", "Lesson").objects.get(pk=pk).mastery_options == "three_sheets"

    def test_the_migrations_can_be_undone_and_applied_again(self, django_user_model):
        migrate(BACKFILLED)
        owner = django_user_model.objects.create_user("g@example.com", password="x", name="G")
        apps = migrate(BACKFILLED)
        pk = self.make(apps, owner.pk, level="expert").pk

        migrate(BEFORE)
        with connection.cursor() as cursor:
            columns = {c.name for c in connection.introspection.get_table_description(cursor, "lessons_lesson")}
        again = migrate(BACKFILLED)

        assert "entry" not in columns and "self_rating_halves" not in columns
        assert again.get_model("lessons", "Lesson").objects.get(pk=pk).level_source == "diagnostic"

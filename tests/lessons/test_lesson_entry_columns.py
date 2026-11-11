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
- the mastery choice has one version since phase 9.8: publishing it moves the stage and records nothing, and the API
  and the model no longer carry a choice version (migration 0021 dropped it)
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
class TestTheChoiceHasNoOldVersion:
    """The three-sheet choice was retired in phase 9.8 (migration 0021): a lesson no longer says which choice it was
    shown, because there is only one."""

    def test_publishing_the_choice_only_moves_the_stage(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC, route="mastery")

        PublishMasteryOptionsNode()(lesson_state, runtime)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_CHOICE

    def test_the_api_does_not_report_a_choice_version(self, signed_in_client, lesson):
        assert "mastery_options" not in signed_in_client.get(f"/api/lessons/{lesson.id}").json()

    def test_the_model_has_no_such_column(self):
        assert "mastery_options" not in {field.name for field in Lesson._meta.get_fields()}


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


@pytest.mark.migration
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
        new.get_model("lessons", "Lesson").objects.filter(pk=pk).update(stage="ready")  # not waiting at it any more

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

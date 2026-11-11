"""Unit under test: the migrations of the quick quiz (`quizzes` 0001 and `lessons` 0015 and 0016): the three new
settings, the quiz tables, and a run that can belong to a quiz instead of a lesson.

Why: the tables of a quiz arrive in a database that already holds lessons and their runs. Every existing run must stay
a lesson run, the settings row must pick up working defaults, the database itself must insist that a run has one
subject, and the whole change must be undoable (going back drops the quiz runs, because a run with no lesson cannot
exist before it).

Use cases:
- migrating forward leaves every existing run on its lesson with no quiz, and the settings row gets the defaults
  (10 lessons, 1,500 tokens, 5 calibration questions)
- after it, a run for a quiz is stored and a run for neither or both is refused by the database
- migrating back removes the runs that belong to a quiz, keeps the lesson runs, and drops the quiz tables
"""

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

# One-time data migration: skipped by the everyday local run; CI and `make check-full` run it (docs/process/testing.md).
pytestmark = pytest.mark.migration

BEFORE = [("lessons", "0014_lesson_followup_link")]
AFTER = [("lessons", "0016_graphrun_quick_quiz")]


def latest():
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes())


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
class TestMigrations:
    def teardown_method(self):
        migrate(latest())

    def lesson_with_run(self, apps, owner_id):
        lesson = apps.get_model("lessons", "Lesson").objects.create(owner_id=owner_id, topic="T")
        run = apps.get_model("lessons", "GraphRun").objects.create(lesson_id=lesson.pk, trigger="start")
        return lesson.pk, run.pk

    def test_existing_runs_stay_on_their_lessons_and_the_settings_get_defaults(self, django_user_model):
        old = migrate(BEFORE)
        owner = django_user_model.objects.create_user("m@example.com", password="x", name="M")
        lesson_id, run_id = self.lesson_with_run(old, owner.pk)
        old.get_model("lessons", "FlowSettings").objects.create(pk=1)

        new = migrate(AFTER)

        run = new.get_model("lessons", "GraphRun").objects.get(pk=run_id)
        assert (run.lesson_id, run.quick_quiz_id) == (lesson_id, None)
        settings = new.get_model("lessons", "FlowSettings").objects.get(pk=1)
        defaults = (settings.quiz_max_source_lessons, settings.quiz_source_token_budget, settings.calibration_questions)
        assert defaults == (10, 1500, 5)

    def test_the_database_insists_that_a_run_has_exactly_one_subject(self, django_user_model):
        new = migrate(AFTER)
        owner = django_user_model.objects.create_user("n@example.com", password="x", name="N")
        lesson_id, _ = self.lesson_with_run(new, owner.pk)
        quiz = new.get_model("quizzes", "QuickQuiz").objects.create(
            owner_id=owner.pk, source_type="topic", topic="Q", config={}, config_hash="h"
        )
        Run = new.get_model("lessons", "GraphRun")

        assert Run.objects.create(quick_quiz_id=quiz.pk, trigger="start", graph="quick_quiz").lesson_id is None
        for fields in ({}, {"lesson_id": lesson_id, "quick_quiz_id": quiz.pk}):
            with pytest.raises(IntegrityError), transaction.atomic():
                Run.objects.create(trigger="start", **fields)

    def test_going_back_drops_the_quiz_runs_and_keeps_the_lesson_runs(self, django_user_model):
        new = migrate(AFTER)
        owner = django_user_model.objects.create_user("o@example.com", password="x", name="O")
        _, kept = self.lesson_with_run(new, owner.pk)
        quiz = new.get_model("quizzes", "QuickQuiz").objects.create(
            owner_id=owner.pk, source_type="topic", topic="Q", config={}, config_hash="h"
        )
        gone = new.get_model("lessons", "GraphRun").objects.create(quick_quiz_id=quiz.pk, trigger="start").pk

        old = migrate(BEFORE)

        runs = old.get_model("lessons", "GraphRun").objects
        assert runs.filter(pk=kept).exists() and not runs.filter(pk=gone).exists()
        assert "quizzes_quickquiz" not in connection.introspection.table_names()

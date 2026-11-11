"""Unit under test: lessons migration 0006 (`level_and_difficulty_names`), which renames the levels and difficulties
stored in every lesson.

Why: it rewrites real learners' lessons. A lesson that opens after it must show its level and its test as before, with
nothing left under a name the code no longer knows, and the migration has to be undoable. The scan at the end is the
guard of the whole rename: it looks in every stored JSON document for a difficulty or a mix with an old name.

Use cases:
- the level of a lesson, its assessment and its plan move to the new names by position, and the documents are stamped
- the questions of a stored test, the mix in the plan and the questions of a practice sheet get the new difficulties
- a document already in the new names (stamped) is not renamed again
- other fields of the lesson, and lessons with nothing to rename, are untouched
- no old difficulty name is left in any stored document (the scan)
- the migration can be undone: old names come back, the stamp goes, basic reads as easy and expert as hard
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# One-time data migration: skipped by the everyday local run; CI and `make check-full` run it (docs/process/testing.md).
pytestmark = pytest.mark.migration

BEFORE = [("lessons", "0005_graphrun_node_timings")]
AFTER = [("lessons", "0006_level_and_difficulty_names")]


def latest():
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes("lessons"))


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def question(number, difficulty):
    return {"id": f"t{number}", "type": "mcq", "difficulty": difficulty, "concept": "hard", "marks": 2}


OLD_TEST = {"questions": [question(1, "easy"), question(2, "medium"), question(3, "hard")]}
OLD_PLAN = {
    "title": "Binary search", "level": "beginner",
    "final_test": {"difficulty_mix": {"easy": 1, "medium": 1, "hard": 1}},
}  # fmt: skip
OLD_ASSESSMENT = {"level": "intermediate", "gaps": []}


def old_text_scan(node):
    """Every old difficulty name or mix key found anywhere in the document."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "difficulty" and value in ("medium", "hard"):
                found.append(value)
            if key == "difficulty_mix":
                found += [k for k in value if k in ("medium", "hard")]
            found += old_text_scan(value)
    elif isinstance(node, list):
        for item in node:
            found += old_text_scan(item)
    return found


@pytest.mark.django_db(transaction=True)
def test_levels_and_difficulties_are_renamed_everywhere_and_the_scan_finds_nothing_left(django_user_model):
    old = migrate(BEFORE)
    Lesson, Material = old.get_model("lessons", "Lesson"), old.get_model("lessons", "StudyMaterial")
    owner = django_user_model.objects.create_user("m@example.com", password="x", name="M")
    old_lesson = Lesson.objects.create(
        owner_id=owner.pk, topic="Binary search", level="beginner", assessment=OLD_ASSESSMENT, plan=OLD_PLAN,
        final_test=OLD_TEST, stage="ready", error="keep me",
    )  # fmt: skip
    bare = Lesson.objects.create(owner_id=owner.pk, topic="Bare", level="", stage="failed")
    current = {"level": "beginner", "level_scheme": 2, "final_test": {"difficulty_mix": {"easy": 3, "basic": 0}}}
    already = Lesson.objects.create(owner_id=owner.pk, topic="Already", level="beginner", plan=current)
    sheet = Material.objects.create(
        lesson=old_lesson, kind="practice_sheet",
        content={"questions": [question(1, "easy"), question(2, "hard")]},
    )  # fmt: skip

    try:
        new = migrate(AFTER)
        Lesson, Material = new.get_model("lessons", "Lesson"), new.get_model("lessons", "StudyMaterial")

        row = Lesson.objects.get(pk=old_lesson.pk)
        assert row.level == "foundation" and row.error == "keep me" and row.topic == "Binary search"
        assert row.assessment == {"level": "proficient", "gaps": [], "level_scheme": 2}
        assert row.plan["level"] == "foundation" and row.plan["level_scheme"] == 2
        assert row.plan["final_test"]["difficulty_mix"] == {
            "easy": 1, "basic": 0, "standard": 1, "difficult": 1, "expert": 0,
        }  # fmt: skip
        assert [q["difficulty"] for q in row.final_test["questions"]] == ["easy", "standard", "difficult"]
        assert row.final_test["questions"][2]["concept"] == "hard"  # a word in the content is not a difficulty
        assert [q["difficulty"] for q in Material.objects.get(pk=sheet.pk).content["questions"]] == [
            "easy", "difficult",
        ]  # fmt: skip

        assert Lesson.objects.get(pk=bare.pk).level == "" and Lesson.objects.get(pk=bare.pk).plan is None
        kept = Lesson.objects.get(pk=already.pk).plan  # a stamped document's level is not renamed again
        assert (kept["level"], kept["level_scheme"]) == ("beginner", 2)
        assert kept["final_test"]["difficulty_mix"] == {
            "easy": 3,
            "basic": 0,
            "standard": 0,
            "difficult": 0,
            "expert": 0,
        }
        assert Lesson.objects.get(pk=already.pk).level == "foundation"  # the column is not stamped: it was old

        for lesson in Lesson.objects.all():
            for document in (lesson.final_test, lesson.plan, lesson.assessment):
                assert old_text_scan(document) == []
        for material in Material.objects.all():
            assert old_text_scan(material.content) == []
    finally:
        migrate(latest())


@pytest.mark.django_db(transaction=True)
def test_the_migration_can_be_undone(django_user_model):
    old = migrate(BEFORE)
    Lesson = old.get_model("lessons", "Lesson")
    owner = django_user_model.objects.create_user("u@example.com", password="x", name="U")
    original = Lesson.objects.create(
        owner_id=owner.pk, topic="T", level="advanced", assessment=OLD_ASSESSMENT, plan=OLD_PLAN, final_test=OLD_TEST
    )

    try:
        new = migrate(AFTER)
        Lesson = new.get_model("lessons", "Lesson")
        row = Lesson.objects.get(pk=original.pk)
        row.final_test = {"questions": [question(1, "basic"), question(2, "expert")]}
        row.save()

        back = migrate(BEFORE)
        restored = back.get_model("lessons", "Lesson").objects.get(pk=original.pk)

        assert restored.level == "advanced"
        assert restored.assessment == OLD_ASSESSMENT and restored.plan == OLD_PLAN
        assert [q["difficulty"] for q in restored.final_test["questions"]] == ["easy", "hard"]
    finally:
        migrate(latest())

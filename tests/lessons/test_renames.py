"""Unit under test: `lessons.renames` (`LevelRename`, `DifficultyRename`, `StoredRenames`), the data behind migration
0006.

Why: stored lessons carry levels and difficulties in several JSON columns. A name left behind breaks a page that is
opened months later (a difficulty the schema no longer knows, a level the meter cannot show), and a "beginner" rewritten
twice would silently move a learner up a level. The rename must reach every place, once, and be undoable.

Use cases:
- level names are rewritten by position (novice to beginner, beginner to foundation, intermediate to proficient,
  advanced to expert), a document is stamped `level_scheme: 2`, and one already stamped is left alone
- a document with nothing in it, or no level, is handled without error
- undoing a stamped document restores the old names and drops the stamp; an unstamped one is left alone
- difficulties are renamed wherever a `difficulty` key is, however deep, and in a `difficulty_mix`, which gains the new
  keys; the input is never changed, other values are never touched
- undoing maps the new difficulties back, basic to easy and expert to hard (lossy), and merges the mix
- renaming twice is the same as once
- every JSON column of every model of the lessons app is named in exactly one of the lists of columns the rename covers
  or leaves alone, so a new column cannot be forgotten
"""

import pytest
from django.apps import apps as django_apps
from django.db import models

from lessons.renames import DifficultyRename, LevelRename, StoredRenames

levels, difficulties = LevelRename(), DifficultyRename()


class TestLevelRename:
    @pytest.mark.parametrize(
        ("old", "new"),
        [("novice", "beginner"), ("beginner", "foundation"), ("intermediate", "proficient"), ("advanced", "expert")],
    )
    def test_a_name_moves_by_position_and_back(self, old, new):
        assert levels.forward_name(old) == new
        assert levels.backward_name(new) == old

    def test_an_unknown_or_blank_name_is_left_alone(self):
        assert levels.forward_name("") == "" and levels.backward_name("guru") == "guru"

    def test_a_document_is_rewritten_and_stamped(self):
        document = {"level": "beginner", "gaps": ["x"]}

        assert levels.forward_document(document) == {"level": "foundation", "gaps": ["x"], "level_scheme": 2}
        assert document == {"level": "beginner", "gaps": ["x"]}

    def test_a_stamped_empty_or_missing_document_is_left_alone(self):
        stamped = {"level": "beginner", "level_scheme": 2}

        assert levels.forward_document(stamped) is stamped
        assert levels.forward_document(None) is None and levels.forward_document({}) == {}

    def test_a_document_without_a_level_is_stamped_with_a_blank_one(self):
        assert levels.forward_document({"title": "x"}) == {"title": "x", "level": "", "level_scheme": 2}

    def test_undoing_a_stamped_document_restores_the_old_names_and_drops_the_stamp(self):
        assert levels.backward_document({"level": "foundation", "level_scheme": 2, "n": 1}) == {
            "level": "beginner", "n": 1,
        }  # fmt: skip

    def test_undoing_an_unstamped_or_empty_document_changes_nothing(self):
        legacy = {"level": "beginner"}

        assert levels.backward_document(legacy) is legacy and levels.backward_document(None) is None


MIX = {"easy": 4, "medium": 4, "hard": 2}
NEW_MIX = {"easy": 4, "basic": 0, "standard": 4, "difficult": 2, "expert": 0}


class TestDifficultyRename:
    def test_every_difficulty_is_renamed_however_deep(self):
        document = {
            "questions": [{"difficulty": "medium", "n": 1}, {"difficulty": "hard"}, {"difficulty": "easy"}],
            "plan": {"final_test": {"difficulty_mix": MIX}},
            "nested": [[{"difficulty": "hard"}]],
        }

        out = difficulties.forward(document)

        assert [q["difficulty"] for q in out["questions"]] == ["standard", "difficult", "easy"]
        assert out["plan"]["final_test"]["difficulty_mix"] == NEW_MIX
        assert out["nested"][0][0]["difficulty"] == "difficult"
        assert document["questions"][0]["difficulty"] == "medium"  # the input is untouched

    def test_other_values_are_never_touched(self):
        document = {"concept": "hard", "question": "a medium question", "difficulty_note": "hard", "marks": 3}

        assert difficulties.forward(document) == document

    def test_a_mix_with_unknown_keys_keeps_their_counts(self):
        assert difficulties.forward({"difficulty_mix": {"easy": 1, "odd": 2}})["difficulty_mix"]["odd"] == 2

    @pytest.mark.parametrize("value", [None, 3, "x", [], {}])
    def test_things_that_hold_no_difficulty_come_back_as_they_were(self, value):
        assert difficulties.forward(value) == value

    def test_renaming_twice_is_the_same_as_once(self):
        document = {"questions": [{"difficulty": "medium"}], "difficulty_mix": MIX}

        once = difficulties.forward(document)

        assert difficulties.forward(once) == once

    def test_undoing_maps_back_with_basic_and_expert_collapsing(self):
        document = {
            "questions": [{"difficulty": d} for d in ("easy", "basic", "standard", "difficult", "expert")],
            "difficulty_mix": {"easy": 1, "basic": 1, "standard": 2, "difficult": 1, "expert": 1},
        }

        out = difficulties.backward(document)

        assert [q["difficulty"] for q in out["questions"]] == ["easy", "easy", "medium", "hard", "hard"]
        assert out["difficulty_mix"] == {"easy": 2, "medium": 2, "hard": 2}

    def test_forward_then_backward_restores_old_data(self):
        document = {"questions": [{"difficulty": "medium"}, {"difficulty": "hard"}], "difficulty_mix": MIX}

        assert difficulties.backward(difficulties.forward(document)) == document


class TestEveryColumnIsAccountedFor:
    def json_columns(self):
        found = set()
        for model in django_apps.get_app_config("lessons").get_models():
            for field in model._meta.get_fields():
                if isinstance(field, models.JSONField):
                    found.add((model.__name__, field.name))
        return found

    def test_each_json_column_is_either_rewritten_or_known_to_hold_neither_name(self):
        covered = set(StoredRenames.DIFFICULTY_COLUMNS) | set(StoredRenames.LEVEL_COLUMNS)
        known = covered | set(StoredRenames.UNTOUCHED_COLUMNS)

        assert self.json_columns() - known == set(), "a new JSON column: does it hold a level or a difficulty?"
        gone = known - self.json_columns()
        assert gone == set(StoredRenames.RETIRED_COLUMNS), "a column that no longer exists is still listed"
        assert covered.isdisjoint(StoredRenames.UNTOUCHED_COLUMNS)

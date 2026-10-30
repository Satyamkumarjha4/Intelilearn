"""Unit under test: `graph.questions.LessonTestBlueprint`, the fixed ten cells of a lesson's test (plan D15).

Why: attempts at one lesson are only comparable if every attempt is worth the same, and a retake only fills the same
cells if the cells are fixed in code. The model no longer chooses the mix, so this table is the test.

Use cases:
- there are ten cells, two for each of the five difficulties, and only objective types (mcq, msq, numerical)
- a quantitative topic is worth 20 marks and any other topic 18, and the type split per difficulty is the plan's table
- the marks of every cell come from the marks table, so a changed table changes the blueprint
- the cells are numbered 0 to 9 and a question id is its cell's number plus one
- the same topic kind always gives the same blueprint
- a blueprint survives being stored as JSON, and a stored one that is wrong is refused
- a lesson made before the blueprint gets one from its old test: quantitative if the old test had a numerical question
- the cells that are not yet filled are the ones missing from a set of accepted indices
"""

from collections import Counter

import pytest

from graph.questions import LessonTestBlueprint, MarksPolicy

QUANTITATIVE = [
    ("easy", "mcq"), ("easy", "mcq"), ("basic", "mcq"), ("basic", "msq"), ("standard", "mcq"),
    ("standard", "numerical"), ("difficult", "msq"), ("difficult", "numerical"), ("expert", "msq"),
    ("expert", "numerical"),
]  # fmt: skip
OTHER = [
    ("easy", "mcq"), ("easy", "mcq"), ("basic", "mcq"), ("basic", "msq"), ("standard", "mcq"), ("standard", "msq"),
    ("difficult", "msq"), ("difficult", "mcq"), ("expert", "msq"), ("expert", "mcq"),
]  # fmt: skip


@pytest.mark.parametrize(("quantitative", "split", "total"), [(True, QUANTITATIVE, 20), (False, OTHER, 18)])
class TestTheTable:
    def test_the_cells_are_the_plans_table(self, quantitative, split, total):
        blueprint = LessonTestBlueprint.for_topic(quantitative)

        assert [(c.difficulty, c.type) for c in blueprint.cells] == split
        assert blueprint.total_marks == total and blueprint.quantitative is quantitative

    def test_each_difficulty_has_two_cells_and_only_objective_types_are_used(self, quantitative, split, total):
        cells = LessonTestBlueprint.for_topic(quantitative).cells

        assert len(cells) == 10
        assert Counter(c.difficulty for c in cells) == dict.fromkeys(
            ["easy", "basic", "standard", "difficult", "expert"], 2
        )
        assert {c.type for c in cells} <= {"mcq", "msq", "numerical"}

    def test_the_marks_of_a_cell_come_from_the_marks_table(self, quantitative, split, total):
        for cell in LessonTestBlueprint.for_topic(quantitative).cells:
            assert cell.marks == MarksPolicy.marks(cell.type, cell.difficulty)


def test_the_cells_are_numbered_from_zero_and_the_question_id_follows_the_number():
    cells = LessonTestBlueprint.for_topic(False).cells

    assert (
        [c.index for c in cells] == list(range(10)) and cells[0].question_id == "t1" and cells[9].question_id == "t10"
    )


def test_the_same_kind_of_topic_always_gives_the_same_blueprint():
    assert LessonTestBlueprint.for_topic(True) == LessonTestBlueprint.for_topic(True)
    assert LessonTestBlueprint.for_topic(True) != LessonTestBlueprint.for_topic(False)


class TestStoring:
    @pytest.mark.parametrize("quantitative", [True, False])
    def test_a_blueprint_survives_json(self, quantitative):
        blueprint = LessonTestBlueprint.for_topic(quantitative)

        assert LessonTestBlueprint.from_json(blueprint.to_json()) == blueprint

    def test_the_json_names_the_total_and_the_flag(self):
        data = LessonTestBlueprint.for_topic(True).to_json()

        assert data["total_marks"] == 20 and data["quantitative"] is True and len(data["cells"]) == 10

    @pytest.mark.parametrize(
        "broken",
        [None, {}, {"quantitative": True}, {"quantitative": True, "cells": []}, {"quantitative": "yes", "cells": [1]}],
    )
    def test_a_stored_blueprint_that_is_wrong_is_refused(self, broken):
        with pytest.raises(ValueError):
            LessonTestBlueprint.from_json(broken)

    def test_a_stored_blueprint_whose_cells_are_not_the_table_is_refused(self):
        data = LessonTestBlueprint.for_topic(False).to_json()
        data["cells"][0]["type"] = "numerical"

        with pytest.raises(ValueError, match="cells"):
            LessonTestBlueprint.from_json(data)


class TestForAnOldLesson:
    def test_a_numerical_question_in_the_old_test_makes_the_topic_quantitative(self):
        old = [{"type": "mcq"}, {"type": "numerical"}, {"type": "short_answer"}]

        assert LessonTestBlueprint.for_old_test(old).quantitative is True

    @pytest.mark.parametrize("old", [[{"type": "mcq"}, {"type": "long_answer"}], [], None])
    def test_no_numerical_question_means_another_kind_of_topic(self, old):
        assert LessonTestBlueprint.for_old_test(old).quantitative is False


def test_the_cells_still_to_fill_are_those_not_accepted():
    blueprint = LessonTestBlueprint.for_topic(False)

    assert [c.index for c in blueprint.missing({0, 1, 2, 3, 4, 5, 6, 7})] == [8, 9]
    assert blueprint.missing(set(range(10))) == ()
    assert len(blueprint.missing(set())) == 10

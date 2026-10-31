"""Unit under test: `graph.questions.quiz_blueprint.QuizBlueprint` and `graph.questions.blueprints.Blueprints`: the
cells
of a quick quiz (a question's type, difficulty, marks and the lesson it is about), and the one reader for stored
blueprints of every kind (plan §6.6).

Why: the model is told, cell by cell, exactly what to write, so the quiz's mix of difficulties and kinds is decided in
code and does not depend on the model. For a quiz from several lessons each lesson's questions are at that lesson's own
level and stay together, so a batch of five covers one or two lessons and never needs the others' summaries.

Use cases:
- a topic quiz has as many cells as questions asked, with the difficulty mix of the learner's level and the marks of the
  marks table
- the kinds picked are dealt out in turn across the cells
- a quiz from lessons has each lesson's share of cells together, in the order given, each with the mix of that lesson's
  own level and carrying the lesson's key
- the total marks are the sum of the cells'; cells are numbered from 0 and their questions are t1, t2…
- the cells still missing are the ones no accepted question fills
- a stored blueprint is read back as it was; one whose cells were changed by hand is refused
- the reader finds a lesson test's blueprint (which has no kind) and a quiz's by what is stored, and refuses the rest
"""

import pytest

from graph.difficulty_mix import DifficultyMix
from graph.levels import Level
from graph.questions import LessonTestBlueprint
from graph.questions.blueprints import Blueprints
from graph.questions.marks import MarksPolicy
from graph.questions.quiz_blueprint import QuizBlueprint, SourcePart


def topic_quiz(count=10, types=("mcq",), level=Level.FOUNDATION) -> QuizBlueprint:
    return QuizBlueprint.for_topic(count, types, level)


class TestATopicQuiz:
    def test_it_has_a_cell_for_every_question(self):
        blueprint = topic_quiz(15)

        assert [cell.index for cell in blueprint.cells] == list(range(15))
        assert [cell.question_id for cell in blueprint.cells][:3] == ["t1", "t2", "t3"]

    @pytest.mark.parametrize("level", list(Level))
    def test_the_difficulties_are_the_mix_of_the_level(self, level):
        blueprint = topic_quiz(20, level=level)
        mix = DifficultyMix.for_level(level, 20)

        for difficulty, wanted in mix.counts.items():
            assert sum(1 for c in blueprint.cells if c.difficulty == difficulty.value) == wanted

    def test_the_cells_go_from_easy_to_hard(self):
        order = ["easy", "basic", "standard", "difficult", "expert"]
        ranks = [order.index(cell.difficulty) for cell in topic_quiz(20).cells]

        assert ranks == sorted(ranks)

    def test_the_marks_are_the_marks_tables_not_a_models(self):
        for cell in topic_quiz(10, types=("mcq", "msq", "numerical")).cells:
            assert cell.marks == MarksPolicy.marks(cell.type, cell.difficulty)

    def test_the_kinds_picked_are_dealt_out_in_turn(self):
        cells = topic_quiz(10, types=("mcq", "msq", "numerical")).cells

        assert [c.type for c in cells] == ["mcq", "msq", "numerical"] * 3 + ["mcq"]

    def test_one_kind_is_every_cell(self):
        assert {c.type for c in topic_quiz(10, types=("numerical",)).cells} == {"numerical"}

    def test_a_topic_quiz_has_no_source_on_its_cells(self):
        assert {c.source for c in topic_quiz().cells} == {""}

    def test_the_total_marks_are_the_sum_of_the_cells(self):
        blueprint = topic_quiz(10)

        assert blueprint.total_marks == sum(c.marks for c in blueprint.cells)

    def test_no_kind_or_a_count_of_nothing_is_refused(self):
        with pytest.raises(ValueError):
            topic_quiz(types=())
        with pytest.raises(ValueError):
            topic_quiz(0)


class TestAQuizFromLessons:
    PARTS = [SourcePart("a", Level.BEGINNER, 4), SourcePart("b", Level.EXPERT, 6)]

    def blueprint(self, types=("mcq", "msq")) -> QuizBlueprint:
        return QuizBlueprint.for_lessons(self.PARTS, types)

    def test_each_lessons_cells_are_together_in_the_order_given(self):
        assert [c.source for c in self.blueprint().cells] == ["a"] * 4 + ["b"] * 6

    def test_each_lessons_difficulties_are_the_mix_of_its_own_level(self):
        cells = self.blueprint().cells
        for part in self.PARTS:
            mine = [c.difficulty for c in cells if c.source == part.key]
            expected = [d.value for d in DifficultyMix.for_level(part.level, part.share).ordered()]
            assert mine == expected

    def test_the_kinds_are_dealt_across_the_whole_quiz_not_one_lesson_at_a_time(self):
        cells = self.blueprint().cells

        assert [c.type for c in cells] == ["mcq", "msq"] * 5

    def test_cells_are_numbered_through_the_whole_quiz(self):
        assert [c.index for c in self.blueprint().cells] == list(range(10))

    def test_a_lesson_with_no_share_is_refused(self):
        with pytest.raises(ValueError, match="share"):
            QuizBlueprint.for_lessons([SourcePart("a", Level.BEGINNER, 0)], ("mcq",))

    def test_no_lessons_are_refused(self):
        with pytest.raises(ValueError):
            QuizBlueprint.for_lessons([], ("mcq",))


class TestMissingCells:
    def test_the_cells_no_accepted_question_fills(self):
        blueprint = topic_quiz(5)

        assert [c.index for c in blueprint.missing({0, 2, 4})] == [1, 3]
        assert blueprint.missing({0, 1, 2, 3, 4}) == ()


class TestStoring:
    def test_a_blueprint_is_read_back_as_it_was(self):
        blueprint = QuizBlueprint.for_lessons(TestAQuizFromLessons.PARTS, ("mcq", "short_answer"))

        assert QuizBlueprint.from_json(blueprint.to_json()) == blueprint

    def test_the_stored_form_says_it_is_a_quiz(self):
        assert topic_quiz().to_json()["kind"] == "quiz"

    def test_cells_changed_by_hand_are_refused(self):
        stored = topic_quiz().to_json()
        stored["cells"][0]["marks"] = 99

        with pytest.raises(ValueError, match="marks"):
            QuizBlueprint.from_json(stored)

    def test_a_kind_that_does_not_exist_is_refused(self):
        stored = topic_quiz().to_json()
        stored["cells"][0]["type"] = "essay"

        with pytest.raises(ValueError):
            QuizBlueprint.from_json(stored)

    @pytest.mark.parametrize("stored", [None, {}, {"kind": "quiz"}, {"kind": "quiz", "cells": []}, "cells"])
    def test_something_that_is_not_a_blueprint_is_refused(self, stored):
        with pytest.raises(ValueError):
            QuizBlueprint.from_json(stored)


class TestReadingAnyBlueprint:
    def test_a_lesson_tests_blueprint_has_no_kind_and_is_read_as_one(self):
        stored = LessonTestBlueprint.for_topic(True).to_json()

        assert Blueprints.from_json(stored) == LessonTestBlueprint.for_topic(True)

    def test_a_quizs_blueprint_is_read_as_one(self):
        blueprint = topic_quiz(10)

        assert Blueprints.from_json(blueprint.to_json()) == blueprint

    def test_anything_else_is_refused(self):
        with pytest.raises(ValueError):
            Blueprints.from_json({"kind": "exam", "cells": [{"index": 0}]})
        with pytest.raises(ValueError):
            Blueprints.from_json(None)

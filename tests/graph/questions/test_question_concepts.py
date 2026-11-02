"""Unit under test: `graph.questions.concepts.QuestionConcepts`: which concepts a question may name, for the questions
of a lesson (plan §9.6, R18).

Why: a quiz result links each weak concept to the page that teaches it. That only works if the concept a question names
is one the lesson's index knows, so a question written for a lesson must name one of that lesson's concepts, copied
exactly. The model is told the list; this class gives the list for each cell, accepts a near-miss in case or spacing by
writing it with the lesson's own spelling, and reports a name that is not on the list. A topic quiz has no lesson, so
nothing is asked of it.

Use cases:
- a lesson's test (or retake) may use any concept of the lesson's plan, for every cell
- a quiz from lessons may use the concepts that were kept in the summary of each cell's own lesson
- a topic quiz, or a state with neither a plan nor a quiz, has no list: any concept is fine
- a question that names an allowed concept in other case or spacing is written with the allowed spelling
- a question that names something else is reported with the list, and is left as it was
- a cell with no list accepts any concept
"""

import pytest
from support.lesson_data import make_plan

from graph.questions import Cell
from graph.questions.concepts import QuestionConcepts


def cell(index: int, source: str = "") -> Cell:
    return Cell(index=index, type="mcq", difficulty="easy", marks=1, source=source)


PLAN_CONCEPTS = [
    "Searching a list", "Sorted data", "Why halving helps", "Halving the range", "The loop invariant",
    "Returning the index", "Time complexity", "Off-by-one pitfalls", "Searching on answers",
]  # fmt: skip


class TestWhichConcepts:
    def test_a_lessons_test_may_use_every_concept_of_its_plan(self):
        allowed = QuestionConcepts.allowed({"plan": make_plan()}, [cell(0), cell(1)])

        assert allowed == [PLAN_CONCEPTS, PLAN_CONCEPTS]

    def test_a_quiz_from_lessons_uses_each_cells_own_lessons_concepts(self):
        data = {"quiz": {"sources": {"a": {"concepts": ["Fractions", "Ratios"]}, "b": {"concepts": ["Decimals"]}}}}

        allowed = QuestionConcepts.allowed(data, [cell(0, "a"), cell(1, "b"), cell(2, "a")])

        assert allowed == [["Fractions", "Ratios"], ["Decimals"], ["Fractions", "Ratios"]]

    def test_a_topic_quiz_has_no_list(self):
        assert QuestionConcepts.allowed({"quiz": {"level": "expert", "sources": {}}}, [cell(0)]) == [None]

    def test_a_state_with_neither_has_no_list(self):
        assert QuestionConcepts.allowed({}, [cell(0), cell(1)]) == [None, None]

    def test_a_cell_whose_lesson_is_unknown_has_no_list(self):
        data = {"quiz": {"sources": {"a": {"concepts": ["Fractions"]}}}}

        assert QuestionConcepts.allowed(data, [cell(0, "zzz")]) == [None]

    def test_a_lesson_without_concepts_in_its_summary_has_no_list(self):
        data = {"quiz": {"sources": {"a": {"concepts": []}}}}

        assert QuestionConcepts.allowed(data, [cell(0, "a")]) == [None]


class TestChecking:
    ALLOWED = [["Halving the range", "Time complexity"]]

    def test_an_allowed_concept_is_fine(self):
        questions = [{"id": "t1", "concept": "Time complexity"}]

        assert QuestionConcepts.problems(questions, self.ALLOWED) == []

    def test_the_spelling_of_the_lesson_replaces_a_near_miss(self):
        questions = [{"id": "t1", "concept": "  halving   THE range "}]

        QuestionConcepts.canonicalise(questions, self.ALLOWED)

        assert questions[0]["concept"] == "Halving the range"
        assert QuestionConcepts.problems(questions, self.ALLOWED) == []

    def test_another_concept_is_reported_with_the_list_and_left_alone(self):
        questions = [{"id": "t1", "concept": "Photosynthesis"}]

        QuestionConcepts.canonicalise(questions, self.ALLOWED)
        problems = QuestionConcepts.problems(questions, self.ALLOWED)

        assert questions[0]["concept"] == "Photosynthesis"
        assert problems == [
            'Question t1: the concept "Photosynthesis" must be one of: Halving the range; Time complexity.'
        ]

    def test_a_cell_with_no_list_accepts_any_concept(self):
        questions = [{"id": "t1", "concept": "Anything"}, {"id": "t2", "concept": "Time complexity"}]

        assert QuestionConcepts.problems(questions, [None, ["Time complexity"]]) == []

    @pytest.mark.parametrize("questions", [[], [{"id": "t1", "concept": "x"}]])
    def test_fewer_lists_than_questions_is_not_an_error(self, questions):
        assert QuestionConcepts.problems(questions, []) == []

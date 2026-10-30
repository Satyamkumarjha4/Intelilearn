"""Unit under test: `graph.questions.CriteriaRebalancer`, which makes the criteria of a short or long answer add up to
the question's marks before the question is validated.

Why: a model cannot be trusted to add. The marks of a question come from the table, so when its criteria add up to
something else the code scales them to fit instead of sending the whole batch back for a sum. Only a question with more
criteria than marks cannot be fitted (each criterion is worth at least one mark), and that goes back to the model with
the reason. Largest-remainder rounding keeps the total exact, whatever the shares were.

Use cases:
- criteria that already add up are returned unchanged
- criteria that add up to too much or too little are scaled in proportion, the total is exactly the question's marks,
  and every criterion keeps at least one mark (table-driven)
- ties in the remainders go to the earlier criterion
- more criteria than marks cannot be fitted and are named as a problem; nothing is changed
- criteria that cannot be read (no list, a zero or a missing mark) are left for the validator to name
- the input is never changed, and the text of each criterion is kept
- the finisher uses it: a short or long answer comes out of `QuestionFinisher` with criteria that add up
"""

import copy

import pytest

from graph.questions import CriteriaRebalancer, QuestionFinisher


def criteria(*marks):
    return [{"text": f"c{n}", "marks": m} for n, m in enumerate(marks, start=1)]


def marks_of(result):
    return [c["marks"] for c in result]


class TestRebalance:
    def test_criteria_that_add_up_are_returned_as_they_are(self):
        fitted, problem = CriteriaRebalancer().rebalance(criteria(2, 1), 3)

        assert marks_of(fitted) == [2, 1] and problem is None

    @pytest.mark.parametrize(
        ("given", "marks", "expected"),
        [
            ((1, 1), 3, [2, 1]),  # too little: the remainder goes to the first
            ((1, 1, 1), 5, [2, 2, 1]),
            ((3, 3), 5, [3, 2]),  # too much: scaled down, the tie goes to the earlier one
            ((4, 4, 4), 6, [2, 2, 2]),
            ((5, 1), 3, [2, 1]),  # every criterion keeps at least one mark
            ((10, 1, 1), 3, [1, 1, 1]),
            ((1, 2, 3), 12, [2, 4, 6]),  # proportional
            ((1, 2), 6, [2, 4]),
            ((1,), 6, [6]),
            ((7, 7, 7, 7), 6, [2, 2, 1, 1]),
        ],
    )
    def test_criteria_are_scaled_to_the_marks_with_at_least_one_mark_each(self, given, marks, expected):
        fitted, problem = CriteriaRebalancer().rebalance(criteria(*given), marks)

        assert marks_of(fitted) == expected and problem is None
        assert sum(marks_of(fitted)) == marks and min(marks_of(fitted)) >= 1

    @pytest.mark.parametrize("marks", range(1, 13))
    @pytest.mark.parametrize("given", [(1,), (2, 1), (1, 1, 1), (5, 3, 2), (9, 1, 1, 1), (3, 3, 3, 3, 3)])
    def test_the_total_is_always_exact_when_there_are_no_more_criteria_than_marks(self, given, marks):
        fitted, problem = CriteriaRebalancer().rebalance(criteria(*given), marks)

        if len(given) > marks:
            assert problem is not None
        else:
            assert problem is None and sum(marks_of(fitted)) == marks and min(marks_of(fitted)) >= 1

    def test_more_criteria_than_marks_are_a_problem_and_nothing_is_changed(self):
        given = criteria(1, 1, 1, 1)

        fitted, problem = CriteriaRebalancer().rebalance(given, 3)

        assert marks_of(fitted) == [1, 1, 1, 1]
        assert problem == "there are 4 criteria for 3 marks: use at most 3 criteria, each worth at least one mark."

    @pytest.mark.parametrize("given", [None, [], criteria(0, 3), criteria(2, "x"), [{"text": "no marks"}]])
    def test_criteria_that_cannot_be_read_are_left_for_the_validator(self, given):
        fitted, problem = CriteriaRebalancer().rebalance(given, 3)

        assert fitted == given and problem is None

    def test_the_input_is_not_changed_and_the_text_is_kept(self):
        given = criteria(1, 1)
        before = copy.deepcopy(given)

        fitted, _ = CriteriaRebalancer().rebalance(given, 5)

        assert given == before and [c["text"] for c in fitted] == ["c1", "c2"]


class TestInTheFinisher:
    SHORT = {
        "id": "t1", "type": "short_answer", "concept": "c", "difficulty": "easy", "question": "Q?",
        "model_answer": "m", "criteria": criteria(1, 1, 1),
    }  # fmt: skip

    def test_a_long_answer_comes_out_with_criteria_that_add_up_to_its_marks(self):
        question = self.SHORT | {"type": "long_answer"}

        (done,), problems = QuestionFinisher().finish([question])  # an easy long answer is worth 5

        assert problems == [] and done["marks"] == 5 and marks_of(done["criteria"]) == [2, 2, 1]

    def test_a_short_answer_with_more_criteria_than_marks_comes_back_as_a_problem(self):
        (done,), problems = QuestionFinisher().finish([self.SHORT])  # an easy short answer is worth 2

        assert problems == [
            "Question t1: there are 3 criteria for 2 marks: use at most 2 criteria, each worth at least one mark."
        ]
        assert done["marks"] == 2

    def test_an_objective_question_has_nothing_to_rebalance(self):
        mcq = {
            "id": "t2", "type": "mcq", "concept": "c", "difficulty": "easy", "question": "Q?",
            "options": ["a", "b", "c", "d"], "correct_index": 0,
        }  # fmt: skip

        (done,), problems = QuestionFinisher().finish([mcq])

        assert problems == [] and "criteria" not in done

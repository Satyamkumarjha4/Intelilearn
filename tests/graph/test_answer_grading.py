"""Unit under test: `graph.grading.AnswerGrader`, which marks test and practice answers that have one right answer
(multiple choice and numerical) and leaves the open-ended ones to be self-checked or graded by a model.

Why: a learner trusts the score. Marking `4.0` wrong against `4`, or accepting `NaN`, teaches them the wrong
thing; and a
grader that guessed at essays would present a made-up mark as fact. The same grader serves practice sheets now and the
lesson test later.

Use cases:
- an mcq is right only for the correct option index; a missing, out-of-range or non-integer answer is wrong
- a numerical answer is right within the tolerance, in any number format a person types (spaces, a unit, 4.0 for 4)
- a numerical answer that is not a number, or not finite, is wrong
- short, long and code answers are not marked here (no verdict, no marks)
- a whole sheet is graded in order, with the automatic score and what is still open
"""

import pytest

from graph.grading import AnswerGrader

grader = AnswerGrader()


def mcq(correct=1, marks=2):
    return {"id": "m", "type": "mcq", "marks": marks, "options": list("abcd"), "correct_index": correct}


def numerical(answer=4.0, tolerance=0.01, marks=3):
    return {"id": "n", "type": "numerical", "marks": marks, "answer": answer, "tolerance": tolerance}


class TestMcq:
    def test_the_correct_option_earns_the_marks(self):
        grade = grader.grade(mcq(), 1)

        assert (grade.correct, grade.awarded, grade.marks) == (True, 2, 2)

    @pytest.mark.parametrize("answer", [0, 3, "dont_know", None, 7, -1, "1", 1.0, True])
    def test_anything_else_earns_nothing(self, answer):
        grade = grader.grade(mcq(), answer)

        assert (grade.correct, grade.awarded) == (False, 0)


class TestNumerical:
    @pytest.mark.parametrize(
        "answer",
        [4, 4.0, "4", " 4.0 ", "4.005", "3.995", "4 steps", "4.0steps", "+4", "0.4e1", 4.01],
        ids=repr,
    )
    def test_is_right_within_the_tolerance_in_any_format_a_person_types(self, answer):
        assert grader.grade(numerical(), answer).correct is True

    @pytest.mark.parametrize(
        "answer", [4.02, "5", "-4", "four", "", "  ", None, "nan", "inf", float("nan"), True, "4 5"], ids=repr
    )
    def test_is_wrong_outside_the_tolerance_or_when_it_is_not_a_number(self, answer):
        grade = grader.grade(numerical(), answer)

        assert (grade.correct, grade.awarded) == (False, 0)

    def test_the_tolerance_is_absolute_and_inclusive(self):
        question = numerical(answer=100, tolerance=0.5)

        assert grader.grade(question, 100.5).correct is True
        assert grader.grade(question, 100.6).correct is False

    def test_a_zero_tolerance_wants_the_exact_value(self):
        question = numerical(answer=7, tolerance=0)

        assert grader.grade(question, "7").correct is True
        assert grader.grade(question, "7.0001").correct is False


class TestOpenEnded:
    @pytest.mark.parametrize("kind", ["short_answer", "long_answer", "code"])
    def test_is_not_marked_here(self, kind):
        grade = grader.grade({"id": "x", "type": kind, "marks": 5}, "some answer")

        assert (grade.correct, grade.awarded, grade.marks) == (None, None, 5)


def test_grading_a_sheet_keeps_the_order_and_totals_the_automatic_marks():
    questions = [mcq(), numerical(), {"id": "s", "type": "short_answer", "marks": 4}, {**mcq(), "id": "m2"}]

    result = grader.grade_all(questions, {"m": 1, "n": "9", "s": "text", "m2": 1})

    assert [g.question_id for g in result.grades] == ["m", "n", "s", "m2"]
    assert (result.awarded, result.available, result.open_marks) == (4, 7, 4)
    assert (result.correct, result.marked) == (2, 3)


def test_an_unanswered_question_counts_as_wrong_for_the_kinds_that_can_be_marked():
    result = grader.grade_all([mcq(), numerical()], {})

    assert [g.correct for g in result.grades] == [False, False]
    assert result.awarded == 0

"""Unit under test: `graph.questions.QuestionFinisher`, which turns the questions a model wrote into the questions we
store: marks from the table, the numerical answer computed from its expression.

Why: both are decided by code, never taken from the model. A model that names its own marks or types its own "answer"
could pay itself a higher score or mark every learner wrong. A bad expression has to come back to the generator as a
problem to fix, not as a lesson with an unanswerable question.

Use cases:
- every question gets the marks of its kind and difficulty, whatever the model wrote
- a numerical question gets `answer` computed from `answer_expr`, rounded to `decimal_precision` places
- an expression that cannot be computed is a named problem and the question gets no answer
- other kinds keep every field they came with, and the input is never changed
- the old difficulty names are tolerated and written back as the new ones
"""

import pytest

from graph.questions import QuestionFinisher

MCQ = {"id": "t1", "type": "mcq", "concept": "c", "difficulty": "hard", "question": "Q?", "options": list("abcd"),
       "correct_index": 0, "marks": 99}  # fmt: skip
NUM = {"id": "t2", "type": "numerical", "concept": "c", "difficulty": "easy", "question": "Q?",
       "answer_expr": "sqrt(3) / 2 * 10", "tolerance": 0.01, "decimal_precision": 2, "unit": "m"}  # fmt: skip


def finish(*questions):
    return QuestionFinisher().finish(list(questions))


def test_every_question_gets_the_marks_of_its_kind_and_difficulty_whatever_the_model_wrote():
    questions, problems = finish(MCQ, NUM | {"difficulty": "expert"})

    assert problems == []
    assert [q["marks"] for q in questions] == [2, 3]  # hard is difficult for a multiple-choice question: 2


def test_the_old_difficulty_names_are_written_back_as_the_new_ones():
    questions, _ = finish(MCQ, MCQ | {"id": "t9", "difficulty": "medium"})

    assert [q["difficulty"] for q in questions] == ["difficult", "standard"]


@pytest.mark.parametrize(("precision", "answer"), [(0, 9.0), (1, 8.7), (2, 8.66), (4, 8.6603)])
def test_a_numerical_answer_is_computed_and_rounded_to_the_precision(precision, answer):
    (question,), problems = finish(NUM | {"decimal_precision": precision})

    assert problems == [] and question["answer"] == answer


def test_an_expression_that_cannot_be_computed_is_a_named_problem_and_gets_no_answer():
    questions, problems = finish(
        NUM | {"answer_expr": "__import__('os').getcwd()"}, NUM | {"id": "t3", "answer_expr": "1/0"}
    )

    assert len(problems) == 2
    assert problems[0].startswith("Question t2: the answer_expr")
    assert "not allowed" in problems[0] and "division by zero" in problems[1].lower()
    assert all("answer" not in q for q in questions)


def test_other_kinds_keep_every_field_and_the_input_is_never_changed():
    before = dict(MCQ)

    (question,), _ = finish(MCQ)

    assert question["options"] == list("abcd") and question["correct_index"] == 0
    assert MCQ == before and MCQ["marks"] == 99


def test_a_question_without_an_expression_is_a_problem():
    _, problems = finish({k: v for k, v in NUM.items() if k != "answer_expr"})

    assert problems == ["Question t2: write the answer as answer_expr."]

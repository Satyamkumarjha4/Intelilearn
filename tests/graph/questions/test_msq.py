"""Unit under test: `graph.questions.MsqType`, the multiple-select question ("choose all that apply") and its partial
marking.

Why: a learner who picks most of the right options should keep most of the marks, and one who picks a wrong option or
nothing should not. The rules are the spec's, in its order, with whole marks only; getting an edge wrong (half of the
correct options, one wrong option among right ones) shifts every score on a test that has an MSQ.

Use cases:
- every combination of marks (2 and 3), number of correct options (2 to 4), correct options picked and wrong options
  picked is marked as the spec says: nothing is 0, any wrong option is 0, all correct is full, at least half of the
  correct ones is full minus 1, anything less is 1
- the spec's own scales: 2 marks give 2 / 1 / 1 / 0, 3 marks give 3 / 2 / 1 / 0
- marks are whole numbers, and a fully right answer is `correct`
- a repeated option counts once; an option out of range, a non-number, a bool or a non-list is a wrong answer
- the shape: 4 to 6 options, at least two correct indices, all different and in range
- only the options are public; the correct indices are the solution
- options must differ and may not say "all of the above"
- feedback names the correct options
"""

from itertools import product

import pytest

from graph.questions import MsqType, QuestionTypes, Score


def question(n_correct=2, n_options=5, marks=2):
    return {
        "id": "t1", "type": "msq", "concept": "c", "difficulty": "easy", "marks": marks, "question": "Pick?",
        "options": [f"opt {i}" for i in range(n_options)], "correct_indices": list(range(n_correct)),
    }  # fmt: skip


def expected(marks, n_correct, picked_right, picked_wrong):
    if picked_right + picked_wrong == 0 or picked_wrong:
        return 0
    if picked_right == n_correct:
        return marks
    if picked_right * 2 >= n_correct:
        return marks - 1
    return 1


def answer(n_correct, picked_right, picked_wrong, n_options=6):
    return list(range(picked_right)) + list(range(n_options - picked_wrong, n_options))


@pytest.mark.parametrize(
    ("marks", "n_correct", "picked_right", "picked_wrong"),
    [
        (m, n, r, w)
        for m, n in product((2, 3), (2, 3, 4))
        for r, w in product(range(n + 1), (0, 1, 2))
    ],
)  # fmt: skip
def test_every_combination_is_marked_as_the_spec_says(marks, n_correct, picked_right, picked_wrong):
    q = question(n_correct, 6, marks)

    score = QuestionTypes.get("msq").score(q, answer(n_correct, picked_right, picked_wrong))

    want = expected(marks, n_correct, picked_right, picked_wrong)
    assert score == Score(want == marks, want)


@pytest.mark.parametrize(
    ("marks", "n_correct", "picked", "awarded"),
    [
        (2, 2, [0, 1], 2), (2, 2, [0], 1), (2, 2, [], 0), (2, 2, [0, 1, 2], 0),
        (3, 2, [0, 1], 3), (3, 2, [0], 2), (3, 2, [2], 0),
        (3, 3, [0, 1, 2], 3), (3, 3, [0, 1], 2), (3, 3, [0], 1), (3, 3, [0, 1, 3], 0),
        (3, 4, [0, 1, 2, 3], 3), (3, 4, [0, 1], 2), (3, 4, [0], 1),
        (2, 4, [0, 1, 2], 1), (2, 4, [0], 1),
    ],
)  # fmt: skip
def test_the_specs_scales(marks, n_correct, picked, awarded):
    assert QuestionTypes.get("msq").score(question(n_correct, 6, marks), picked).awarded == awarded


def test_marks_are_whole_numbers_and_a_full_answer_is_correct():
    score = QuestionTypes.get("msq").score(question(3, 6, 3), [0, 1, 2])

    assert isinstance(score.awarded, int) and score.correct is True


def test_a_repeated_option_counts_once():
    assert QuestionTypes.get("msq").score(question(2), [0, 0, 1]).awarded == 2
    assert QuestionTypes.get("msq").score(question(2), [0, 0]).awarded == 1


@pytest.mark.parametrize(
    "bad", [[7], [-1], [0, 9], ["0"], [None], [True], [0, True], [1.0], "0", 0, None, {"0": 1}, [[0]]]
)
def test_an_invalid_answer_is_wrong_and_never_raises(bad):
    assert QuestionTypes.get("msq").score(question(2), bad) == Score(False, 0)


class TestShape:
    def test_a_complete_question_misses_nothing(self):
        assert MsqType().missing_fields(question()) == []

    @pytest.mark.parametrize("count", [4, 5, 6])
    def test_four_to_six_options_are_fine(self, count):
        assert MsqType().missing_fields(question(2, count)) == []

    @pytest.mark.parametrize("count", [3, 7])
    def test_other_option_counts_are_named(self, count):
        assert "options (4 to 6)" in MsqType().missing_fields(question(2, count))

    @pytest.mark.parametrize("indices", [[0], [], None, [0, 0], [0, 9], [-1, 0], [0, True], ["a", 1], [0, 1.0]])
    def test_bad_correct_indices_are_named(self, indices):
        assert "correct_indices (at least 2 different options)" in MsqType().missing_fields(
            question() | {"correct_indices": indices}
        )

    def test_the_options_are_public_and_the_indices_are_the_solution(self):
        kind, q = MsqType(), question()

        assert set(kind.public(q)) == {"id", "type", "concept", "difficulty", "marks", "question", "options"}
        assert kind.solution(q) == {"correct_indices": [0, 1]}

    def test_options_must_differ_and_not_say_all_of_the_above(self):
        assert MsqType().problems(question() | {"options": ["a", "A", "b", "c"]}, "Q")
        assert MsqType().problems(question() | {"options": ["a", "b", "c", "None of the above"]}, "Q")
        assert MsqType().problems(question(), "Q") == []

    def test_feedback_names_the_correct_options(self):
        text = MsqType().expected_text(question() | {"options": ["red", "green", "blue", "pink", "grey"]})

        assert text == 'The correct answers are "red" and "green".'
        assert MsqType().expected_text(question(3)) == 'The correct answers are "opt 0", "opt 1" and "opt 2".'

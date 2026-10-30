"""Unit under test: the point-valued criteria of short and long answers (`ShortAnswerType`, `LongAnswerType`) and
`graph.questions.LegacyQuestionAdapter`, which gives lessons written before them the same criteria.

Why: "partial marks for an open answer" only works if everyone agrees what each mark was for. A model that grades with
criteria that add up to the wrong total, or with a zero-mark criterion, makes marks that cannot be explained; and old
lessons (key points, a bare rubric, code questions) must keep rendering and grading without rewriting history.

Use cases:
- a new short or long answer needs a model answer and criteria; each criterion has text and a positive whole number of
  marks, and the criteria add up to the question's marks
- criteria that do not add up, a zero or fractional criterion, or an empty text are named as problems
- an old short answer's key points become criteria: marks split evenly with the remainder on the first, and when there
  are more points than marks the points are grouped so every criterion is worth at least one mark
- an old long answer's rubric and an old code question become criteria the same way
- a question that already has criteria is left as it is, and so is any other kind
- the adapter never changes its input
- the solution of a normalised question holds the model answer and the criteria
"""

import pytest

from graph.questions import LegacyQuestionAdapter, QuestionTypes

SHORT = {"id": "t1", "type": "short_answer", "concept": "c", "difficulty": "easy", "marks": 2, "question": "Q?",
         "model_answer": "m",
         "criteria": [{"text": "names the idea", "marks": 1}, {"text": "gives an example", "marks": 1}]}  # fmt: skip
LONG = {"id": "t2", "type": "long_answer", "concept": "c", "difficulty": "easy", "marks": 5, "question": "Q?",
        "model_answer": "m", "criteria": [{"text": "a", "marks": 3}, {"text": "b", "marks": 2}]}  # fmt: skip


class TestNewQuestions:
    @pytest.mark.parametrize("question", [SHORT, LONG])
    def test_a_complete_question_misses_nothing_and_has_no_problems(self, question):
        kind = QuestionTypes.of(question)

        assert kind.missing_fields(question) == [] and kind.problems(question, "Question t1") == []

    @pytest.mark.parametrize("question", [SHORT, LONG])
    @pytest.mark.parametrize("field", ["model_answer", "criteria"])
    def test_what_is_missing_is_named(self, question, field):
        assert field in QuestionTypes.of(question).missing_fields(question | {field: None})

    def test_criteria_that_do_not_add_up_to_the_marks_are_a_problem(self):
        problems = QuestionTypes.of(SHORT).problems(SHORT | {"marks": 3}, "Question t1")

        assert problems == ["Question t1: the criteria are worth 2 marks together; the question is worth 3."]

    @pytest.mark.parametrize(
        "criteria",
        [
            [{"text": "a", "marks": 0}, {"text": "b", "marks": 2}],
            [{"text": "a", "marks": -1}, {"text": "b", "marks": 3}],
            [{"text": "a", "marks": 1.5}, {"text": "b", "marks": 0.5}],
            [{"text": "  ", "marks": 1}, {"text": "b", "marks": 1}],
        ],
    )
    def test_a_zero_negative_fractional_or_unnamed_criterion_is_a_problem(self, criteria):
        problems = QuestionTypes.of(SHORT).problems(SHORT | {"criteria": criteria}, "Question t1")

        assert any("whole number of marks" in p or "describe" in p for p in problems)

    def test_the_criteria_and_model_answer_are_the_solution(self):
        assert set(QuestionTypes.of(SHORT).solution(SHORT)) == {"model_answer", "criteria"}

    def test_the_criteria_are_never_public(self):
        assert "criteria" not in QuestionTypes.of(SHORT).public(SHORT)
        assert "model_answer" not in QuestionTypes.of(LONG).public(LONG)


class TestLegacyAdapter:
    def old_short(self, marks=2, points=("halving", "ordering")):
        return {"id": "t1", "type": "short_answer", "marks": marks, "question": "Q?", "model_answer": "m",
                "key_points": list(points)}  # fmt: skip

    def old_long(self, marks=5, rubric=("states it", "shows why", "gives an example")):
        return {"id": "t2", "type": "long_answer", "marks": marks, "question": "Q?", "model_answer": "m",
                "rubric": list(rubric)}  # fmt: skip

    @pytest.mark.parametrize(
        ("marks", "points", "split"),
        [
            (2, ("a", "b"), [1, 1]),
            (3, ("a", "b"), [2, 1]),
            (4, ("a", "b", "c"), [2, 1, 1]),
            (5, ("a", "b", "c"), [2, 2, 1]),
            (6, ("a", "b", "c"), [2, 2, 2]),
            (3, ("a",), [3]),
        ],
    )
    def test_key_points_split_the_marks_evenly_with_the_remainder_first(self, marks, points, split):
        out = LegacyQuestionAdapter.normalise(self.old_short(marks, points))

        assert [c["marks"] for c in out["criteria"]] == split
        assert [c["text"] for c in out["criteria"]] == list(points)
        assert sum(split) == marks

    def test_more_points_than_marks_are_grouped_so_every_criterion_is_worth_a_mark(self):
        out = LegacyQuestionAdapter.normalise(self.old_short(2, ("a", "b", "c", "d", "e")))

        assert [c["marks"] for c in out["criteria"]] == [1, 1]
        assert [c["text"] for c in out["criteria"]] == ["a; b; c", "d; e"]

    def test_a_rubric_becomes_criteria_the_same_way(self):
        out = LegacyQuestionAdapter.normalise(self.old_long())

        assert [c["marks"] for c in out["criteria"]] == [2, 2, 1]

    def test_an_old_code_question_becomes_one_criterion_judged_against_the_reference(self):
        code = {"id": "t3", "type": "code", "marks": 5, "question": "Q?", "language": "python",
                "reference_solution": "x", "test_cases": [{"input": "1", "expected_output": "1"}]}  # fmt: skip

        out = LegacyQuestionAdapter.normalise(code)

        assert len(out["criteria"]) == 1 and out["criteria"][0]["marks"] == 5
        assert "reference solution" in out["criteria"][0]["text"]

    def test_a_question_with_criteria_or_of_another_kind_is_left_as_it_is(self):
        mcq = {"id": "t4", "type": "mcq", "marks": 1, "question": "Q?", "options": list("abcd"), "correct_index": 0}

        assert LegacyQuestionAdapter.normalise(SHORT) == SHORT
        assert LegacyQuestionAdapter.normalise(mcq) == mcq

    def test_a_question_with_nothing_to_turn_into_criteria_gets_one_for_the_whole_answer(self):
        bare = self.old_short(2, ()) | {"key_points": None}

        out = LegacyQuestionAdapter.normalise(bare)

        assert out["criteria"] == [{"text": "The answer is complete and correct.", "marks": 2}]

    def test_the_input_is_never_changed(self):
        old = self.old_short()
        before = dict(old)

        LegacyQuestionAdapter.normalise(old)

        assert old == before and "criteria" not in old

    def test_a_normalised_old_question_is_valid_new_style(self):
        out = LegacyQuestionAdapter.normalise(self.old_long())

        assert QuestionTypes.of(out).problems(out, "Q") == []
        assert set(QuestionTypes.of(out).solution(out)) >= {"model_answer", "criteria"}

"""Unit under test: `graph.questions`, the kinds of question (`QuestionType` and its subclasses) and the registry that
finds them (`QuestionTypes`).

Why: how a question is shaped, shown, marked and explained used to be spread over six `if kind ==` ladders. If one kind
drifts from another (a field shown before answering, an answer marked differently on a practice sheet than in a test),
a learner sees an answer key early or gets a different mark depending on where they answered.

Use cases:
- every kind is registered by its key, and an unknown key is refused
- a question of each kind is checked for its required fields, and what is missing is named
- only the fields on a kind's allowlist are shown before answering (nothing from the answer key), and the solution holds
  exactly the answer-key fields of that kind
- a multiple-choice answer is right only for the exact option index (not a bool, a string or another index)
- a numerical answer is right within the tolerance and understands `4`, `4.0`, `4 steps` and `1e2`, and nothing else
- the open-ended kinds are not marked here, and say so
- feedback says what the right answer is for the kinds that have one
- multiple-choice options must all differ and not say "all of the above"; legacy code in Python must parse
"""

import pytest

from graph.questions import (
    CodeType,
    LongAnswerType,
    McqType,
    NumericalType,
    QuestionTypes,
    Score,
    ShortAnswerType,
    UnknownQuestionType,
)

MCQ = {"id": "t1", "type": "mcq", "concept": "c", "difficulty": "easy", "marks": 2, "question": "Q?",
       "options": ["a", "b", "c", "d"], "correct_index": 2, "explanation": "private"}  # fmt: skip
NUMERICAL = {"id": "t2", "type": "numerical", "concept": "c", "difficulty": "easy", "marks": 3, "question": "Q?",
             "answer_expr": "2 ** 2", "answer": 4.0, "tolerance": 0.5, "decimal_precision": 1,
             "unit": "steps"}  # fmt: skip
SHORT = {"id": "t3", "type": "short_answer", "concept": "c", "difficulty": "easy", "marks": 2, "question": "Q?",
         "model_answer": "m", "criteria": [{"text": "k", "marks": 2}]}  # fmt: skip
LONG = {"id": "t4", "type": "long_answer", "concept": "c", "difficulty": "easy", "marks": 5, "question": "Q?",
        "model_answer": "m", "criteria": [{"text": "r", "marks": 5}]}  # fmt: skip
CODE = {"id": "t5", "type": "code", "concept": "c", "difficulty": "easy", "marks": 5, "question": "Q?",
        "language": "python", "starter_code": "def f(): ...", "reference_solution": "def f(): return 1",
        "test_cases": [{"input": "", "expected_output": "1"}]}  # fmt: skip


class TestRegistry:
    def test_every_kind_is_registered_by_its_key(self):
        assert QuestionTypes.keys() == ("mcq", "msq", "numerical", "short_answer", "long_answer", "code")
        assert isinstance(QuestionTypes.get("mcq"), McqType)
        assert isinstance(QuestionTypes.get("numerical"), NumericalType)
        assert isinstance(QuestionTypes.get("short_answer"), ShortAnswerType)
        assert isinstance(QuestionTypes.get("long_answer"), LongAnswerType)
        assert isinstance(QuestionTypes.get("code"), CodeType)

    def test_a_question_is_found_by_its_type(self):
        assert QuestionTypes.of(MCQ) is QuestionTypes.get("mcq")

    def test_an_unknown_key_is_refused(self):
        with pytest.raises(UnknownQuestionType):
            QuestionTypes.get("essay")


class TestShape:
    @pytest.mark.parametrize("question", [MCQ, NUMERICAL, SHORT, LONG, CODE])
    def test_a_complete_question_misses_nothing(self, question):
        assert QuestionTypes.of(question).missing_fields(question) == []

    @pytest.mark.parametrize(
        ("question", "removed", "named"),
        [
            (MCQ, {"options": ["a", "b"]}, "options (exactly 4)"),
            (MCQ, {"correct_index": 4}, "correct_index (0-3)"),
            (MCQ, {"correct_index": None}, "correct_index (0-3)"),
            (NUMERICAL, {"answer_expr": None}, "answer_expr"),
            (NUMERICAL, {"answer_expr": "  "}, "answer_expr"),
            (NUMERICAL, {"decimal_precision": 7}, "decimal_precision (0-6)"),
            (NUMERICAL, {"decimal_precision": None}, "decimal_precision (0-6)"),
            (NUMERICAL, {"tolerance": -1}, "tolerance (>= 0)"),
            (NUMERICAL, {"tolerance": None}, "tolerance (>= 0)"),
            (SHORT, {"model_answer": ""}, "model_answer"),
            (SHORT, {"criteria": []}, "criteria"),
            (LONG, {"model_answer": None}, "model_answer"),
            (LONG, {"criteria": None}, "criteria"),
            (CODE, {"language": ""}, "language"),
            (CODE, {"reference_solution": None}, "reference_solution"),
            (CODE, {"test_cases": []}, "test_cases"),
        ],
    )
    def test_what_is_missing_or_wrong_is_named(self, question, removed, named):
        assert named in QuestionTypes.of(question).missing_fields(question | removed)


class TestWhatIsShown:
    @pytest.mark.parametrize(
        ("question", "shown"),
        [
            (MCQ, {"id", "type", "concept", "difficulty", "marks", "question", "options"}),
            (NUMERICAL, {"id", "type", "concept", "difficulty", "marks", "question", "unit", "decimal_precision"}),
            (SHORT, {"id", "type", "concept", "difficulty", "marks", "question"}),
            (LONG, {"id", "type", "concept", "difficulty", "marks", "question"}),
            (CODE, {"id", "type", "concept", "difficulty", "marks", "question", "language", "starter_code"}),
        ],
    )
    def test_only_the_allowlist_of_the_kind_is_public(self, question, shown):
        assert set(QuestionTypes.of(question).public(question)) == shown

    def test_a_field_of_another_kind_is_not_public(self):
        assert "options" not in QuestionTypes.of(NUMERICAL).public(NUMERICAL | {"options": ["x"]})
        assert "unit" not in QuestionTypes.of(MCQ).public(MCQ | {"unit": "m"})

    @pytest.mark.parametrize(
        ("question", "fields"),
        [
            (MCQ, {"correct_index"}),
            (NUMERICAL, {"answer", "tolerance", "unit"}),
            (SHORT, {"model_answer", "criteria"}),
            (LONG, {"model_answer", "criteria"}),
            (CODE, {"reference_solution", "test_cases"}),  # criteria appear once the adapter has run
        ],
    )
    def test_the_solution_holds_the_answer_key_fields_of_the_kind(self, question, fields):
        assert set(QuestionTypes.of(question).solution(question)) == fields

    def test_no_public_field_is_an_answer_key_field(self):
        for key in QuestionTypes.keys():
            kind = QuestionTypes.get(key)
            assert not set(kind.public_fields) & (set(kind.solution_fields) - {"unit"})


class TestScoring:
    @pytest.mark.parametrize(("answer", "right"), [(2, True), (1, False), (None, False), ("2", False), (True, False)])
    def test_multiple_choice_is_right_only_for_the_exact_index(self, answer, right):
        assert QuestionTypes.of(MCQ).score(MCQ, answer) == Score(right, 2 if right else 0)

    @pytest.mark.parametrize(
        ("answer", "right"),
        [(4, True), (4.5, True), (3.5, True), (3.4, False), ("4", True), ("4.0", True), ("4 steps", True),
         ("  4.5 ", True), ("0.4e1", True), ("four", False), ("", False), (None, False), (True, False),
         (float("nan"), False), (float("inf"), False)],
    )  # fmt: skip
    def test_numerical_is_right_within_the_tolerance(self, answer, right):
        assert QuestionTypes.of(NUMERICAL).score(NUMERICAL, answer) == Score(right, 3 if right else 0)

    @pytest.mark.parametrize("question", [SHORT, LONG, CODE])
    def test_open_ended_kinds_are_not_marked_here(self, question):
        kind = QuestionTypes.of(question)

        assert kind.score(question, "anything") == Score.needs_judgement()
        assert not kind.auto_scored

    def test_the_kinds_with_one_right_answer_are_auto_scored(self):
        assert QuestionTypes.get("mcq").auto_scored and QuestionTypes.get("numerical").auto_scored


class TestFeedback:
    def test_a_wrong_multiple_choice_answer_names_the_right_option(self):
        assert QuestionTypes.of(MCQ).expected_text(MCQ) == 'The correct answer is "c".'

    def test_a_wrong_number_says_what_was_expected_and_how_close_counts(self):
        text = QuestionTypes.of(NUMERICAL).expected_text(NUMERICAL)

        assert text == "The expected answer is 4 steps (accepted within ±0.5)."

    def test_open_ended_kinds_have_no_expected_text(self):
        assert QuestionTypes.of(SHORT).expected_text(SHORT) == ""


class TestRules:
    def test_options_must_all_differ(self):
        problems = QuestionTypes.of(MCQ).problems(MCQ | {"options": ["a", "A", "c", "d"]}, "Question t1")

        assert problems == ["Question t1: options must all be different."]

    def test_all_of_the_above_is_refused(self):
        problems = QuestionTypes.of(MCQ).problems(MCQ | {"options": ["a", "b", "c", "All of the above"]}, "Q")

        assert any("all/none of the above" in p for p in problems)

    def test_legacy_python_code_must_parse(self):
        bad = CODE | {"reference_solution": "def f(:"}

        problems = QuestionTypes.of(bad).problems(bad, "Question t5")

        assert len(problems) == 1 and problems[0].startswith("Question t5 reference solution is not valid Python")

    def test_other_languages_and_other_kinds_are_not_parsed(self):
        assert QuestionTypes.of(CODE).problems(CODE | {"language": "java", "reference_solution": "x ="}, "Q") == []
        assert QuestionTypes.of(SHORT).problems(SHORT, "Q") == []

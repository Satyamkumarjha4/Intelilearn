"""Unit under test: `graph.schemas.study` (CheatSheet, RevisionSheet, PracticeSheet, MATERIAL_SCHEMAS) and the shared
`TestQuestion` / `public_question` in `graph.schemas.lesson`.

Why: these models are the contract with the LLM (they become the structured-output schema) and with the fixed frontend
templates that render them. A sheet that parses but is missing a field breaks a template; a question type that accepts
a missing answer cannot be graded; `public_question` is what keeps solutions out of the browser.

Use cases:
- each sheet kind round-trips through JSON and is found by its kind
- an unknown kind has no schema
- every question type demands its own fields (mcq options and index, numerical answer and tolerance, short and long
  model answers with points or rubric, code language/solution/test cases) and rejects what is missing
- an mcq has exactly four options and an index among them
- the public view of a question never contains a solution field, for any type
"""

import pytest
from pydantic import ValidationError
from support.study_data import make_cheat_sheet, make_practice_sheet, make_revision_sheet

from graph.schemas import MATERIAL_SCHEMAS, CheatSheet, PracticeSheet, RevisionSheet, public_question
from graph.schemas import lesson as lesson_schemas  # (a bare `TestQuestion` import would be collected by pytest)

BASE = {"id": "t1", "concept": "c", "difficulty": "easy", "marks": 2, "question": "Q?"}


@pytest.mark.parametrize(
    ("kind", "schema", "make"),
    [
        ("cheat_sheet", CheatSheet, make_cheat_sheet),
        ("revision_sheet", RevisionSheet, make_revision_sheet),
        ("practice_sheet", PracticeSheet, make_practice_sheet),
    ],
)
def test_each_sheet_round_trips_and_is_found_by_its_kind(kind, schema, make):
    data = make()

    assert MATERIAL_SCHEMAS[kind] is schema
    assert schema.model_validate(data).model_dump(mode="json") == data


def test_an_unknown_kind_has_no_schema():
    assert "wallpaper" not in MATERIAL_SCHEMAS


class TestQuestionFields:
    @pytest.mark.parametrize(
        ("fields", "missing"),
        [
            ({"type": "mcq", "correct_index": 0}, "options"),
            ({"type": "mcq", "options": list("abc"), "correct_index": 0}, "options"),
            ({"type": "mcq", "options": list("abcd")}, "correct_index"),
            ({"type": "mcq", "options": list("abcd"), "correct_index": 4}, "correct_index"),
            ({"type": "numerical", "tolerance": 0.1}, "answer"),
            ({"type": "numerical", "answer": 1.0}, "tolerance"),
            ({"type": "numerical", "answer": 1.0, "tolerance": -1}, "tolerance"),
            ({"type": "short_answer", "key_points": ["a"]}, "model_answer"),
            ({"type": "short_answer", "model_answer": "a"}, "key_points"),
            ({"type": "long_answer", "model_answer": "a"}, "rubric"),
            ({"type": "long_answer", "rubric": ["a"]}, "model_answer"),
            (
                {"type": "code", "reference_solution": "x", "test_cases": [{"input": "1", "expected_output": "1"}]},
                "language",
            ),
            (
                {"type": "code", "language": "python", "test_cases": [{"input": "1", "expected_output": "1"}]},
                "reference_solution",
            ),
            ({"type": "code", "language": "python", "reference_solution": "x"}, "test_cases"),
        ],
        ids=lambda v: v if isinstance(v, str) else v["type"],
    )
    def test_rejects_a_question_missing_what_its_type_needs(self, fields, missing):
        with pytest.raises(ValidationError, match=missing):
            lesson_schemas.TestQuestion(**BASE, **fields)

    @pytest.mark.parametrize(
        "fields",
        [
            {"type": "mcq", "options": list("abcd"), "correct_index": 3},
            {"type": "numerical", "answer": 2.5, "tolerance": 0},
            {"type": "short_answer", "model_answer": "a", "key_points": ["p"]},
            {"type": "long_answer", "model_answer": "a", "rubric": ["r"]},
            {"type": "code", "language": "python", "reference_solution": "x = 1",
             "test_cases": [{"input": "1", "expected_output": "1"}]},
        ],
        ids=lambda f: f["type"],
    )  # fmt: skip
    def test_accepts_a_complete_question(self, fields):
        assert lesson_schemas.TestQuestion(**BASE, **fields).type == fields["type"]

    def test_marks_stay_between_one_and_twenty(self):
        for marks in (0, 21):
            with pytest.raises(ValidationError):
                lesson_schemas.TestQuestion(
                    **{**BASE, "marks": marks}, type="short_answer", model_answer="a", key_points=["p"]
                )


SOLUTION_FIELDS = {"correct_index", "answer", "tolerance", "model_answer", "key_points", "rubric", "reference_solution",
                   "test_cases"}  # fmt: skip


def test_the_public_view_of_a_question_never_contains_a_solution():
    questions = make_practice_sheet()["questions"]
    questions.append(
        {**BASE, "type": "code", "language": "python", "starter_code": "pass", "reference_solution": "x = 1",
         "test_cases": [{"input": "1", "expected_output": "1"}], "difficulty": "hard"}
    )  # fmt: skip

    for question in questions:
        assert not SOLUTION_FIELDS & set(public_question(question))


def test_the_public_view_keeps_what_the_learner_needs_to_answer():
    mcq = next(q for q in make_practice_sheet()["questions"] if q["type"] == "mcq")

    public = public_question(mcq)

    assert public["options"] == mcq["options"] and public["question"] == mcq["question"]
    numerical = public_question(next(q for q in make_practice_sheet()["questions"] if q["type"] == "numerical"))
    assert numerical["unit"] == "steps" and "options" not in numerical

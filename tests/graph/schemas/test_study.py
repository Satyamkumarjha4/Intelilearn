"""Unit under test: `graph.schemas.study` (CheatSheet, RevisionSheet, PracticeSheet, MATERIAL_SCHEMAS) and the shared
`TestQuestion` / `public_question` in `graph.schemas.lesson`.

Why: these models are the contract with the LLM (they become the structured-output schema) and with the fixed frontend
templates that render them. A sheet that parses but is missing a field breaks a template; a question type that accepts
a missing answer cannot be graded; `public_question` is what keeps solutions out of the browser.

Use cases:
- each sheet kind round-trips through JSON and is found by its kind
- an unknown kind has no schema
- every question type demands its own fields (mcq options and index, msq options and correct indices, numerical
  expression, tolerance and precision, short and long model answers with criteria) and rejects what is missing
- a model is never asked for marks or for the numerical answer: those fields are not in what it writes
- an mcq has exactly four options and an index among them
- the public view of a question never contains a solution field, for any type, stored today or before criteria
"""

import pytest
from pydantic import ValidationError
from support.study_data import make_cheat_sheet, make_practice_sheet, make_revision_sheet

from graph.schemas import MATERIAL_SCHEMAS, CheatSheet, PracticeSheet, RevisionSheet, public_question
from graph.schemas import lesson as lesson_schemas  # (a bare `TestQuestion` import would be collected by pytest)

BASE = {"id": "t1", "concept": "c", "difficulty": "easy", "question": "Q?"}
CRITERIA = [{"text": "a", "marks": 1}, {"text": "b", "marks": 1}]


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
    written = dict(data)  # a model writes no marks and no computed answer
    if "questions" in data:
        written["questions"] = [{k: v for k, v in q.items() if k not in ("marks", "answer")} for q in data["questions"]]

    assert MATERIAL_SCHEMAS[kind] is schema
    assert schema.model_validate(written).model_dump(mode="json") == written


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
            ({"type": "msq", "correct_indices": [0, 1]}, "options"),
            ({"type": "msq", "options": list("abc"), "correct_indices": [0, 1]}, "options"),
            ({"type": "msq", "options": list("abcde")}, "correct_indices"),
            ({"type": "msq", "options": list("abcde"), "correct_indices": [0]}, "correct_indices"),
            ({"type": "msq", "options": list("abcde"), "correct_indices": [0, 7]}, "correct_indices"),
            ({"type": "numerical", "tolerance": 0.1, "decimal_precision": 1}, "answer_expr"),
            ({"type": "numerical", "answer_expr": "1", "decimal_precision": 1}, "tolerance"),
            ({"type": "numerical", "answer_expr": "1", "tolerance": -1, "decimal_precision": 1}, "tolerance"),
            ({"type": "numerical", "answer_expr": "1", "tolerance": 0.1}, "decimal_precision"),
            ({"type": "numerical", "answer_expr": "1", "tolerance": 0.1, "decimal_precision": 9}, "decimal_precision"),
            ({"type": "short_answer", "criteria": CRITERIA}, "model_answer"),
            ({"type": "short_answer", "model_answer": "a"}, "criteria"),
            ({"type": "long_answer", "model_answer": "a"}, "criteria"),
            ({"type": "long_answer", "criteria": CRITERIA}, "model_answer"),
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
            {"type": "msq", "options": list("abcde"), "correct_indices": [0, 4]},
            {"type": "numerical", "answer_expr": "sqrt(3) / 2 * 10", "tolerance": 0, "decimal_precision": 2},
            {"type": "short_answer", "model_answer": "a", "criteria": CRITERIA},
            {"type": "long_answer", "model_answer": "a", "criteria": CRITERIA},
        ],
        ids=lambda f: f["type"],
    )
    def test_accepts_a_complete_question(self, fields):
        assert lesson_schemas.TestQuestion(**BASE, **fields).type == fields["type"]

    def test_a_criterion_is_worth_at_least_one_mark(self):
        with pytest.raises(ValidationError):
            lesson_schemas.TestQuestion(
                **BASE, type="short_answer", model_answer="a", criteria=[{"text": "a", "marks": 0}]
            )

    def test_a_model_is_never_asked_for_marks_or_the_numerical_answer(self):
        fields = set(lesson_schemas.TestQuestion.model_fields)

        assert "marks" not in fields and "answer" not in fields

    def test_the_old_code_type_and_difficulty_names_are_not_something_a_model_may_write(self):
        with pytest.raises(ValidationError):
            lesson_schemas.TestQuestion(**BASE, type="code")
        with pytest.raises(ValidationError):
            lesson_schemas.TestQuestion(
                **{**BASE, "difficulty": "medium"}, type="mcq", options=list("abcd"), correct_index=0
            )


DENIED = {
    "correct_index", "correct_indices", "answer", "answer_expr", "tolerance", "model_answer", "criteria", "key_points",
    "rubric", "reference_solution", "test_cases", "explanation",
}  # fmt: skip
STORED = {
    "mcq": {"options": list("abcd"), "correct_index": 1},
    "msq": {"options": list("abcde"), "correct_indices": [0, 2]},
    "numerical": {"answer_expr": "2 ** 2", "answer": 4.0, "tolerance": 0.5, "decimal_precision": 1, "unit": "steps"},
    "short_answer": {"model_answer": "m", "criteria": CRITERIA},
    "long_answer": {"model_answer": "m", "criteria": CRITERIA},
    # lessons from before criteria and before the code type went away
    "legacy short_answer": {"type": "short_answer", "model_answer": "m", "key_points": ["p"]},
    "legacy long_answer": {"type": "long_answer", "model_answer": "m", "rubric": ["r"]},
    "legacy code": {"type": "code", "language": "python", "starter_code": "pass", "reference_solution": "x = 1",
                    "test_cases": [{"input": "1", "expected_output": "1"}]},
}  # fmt: skip


@pytest.mark.parametrize("name", STORED)
def test_the_public_view_of_a_question_never_contains_a_solution(name):
    fields = STORED[name]
    question = {**BASE, "marks": 2, "type": name, "explanation": "private", "hint": "stray", **fields}
    question |= {"type": fields.get("type", name)}

    public = public_question(question)

    assert not DENIED & set(public), f"leaked: {DENIED & set(public)}"
    assert set(public) <= {"id", "type", "concept", "difficulty", "marks", "question", "options", "unit",
                           "decimal_precision", "language", "starter_code"}  # fmt: skip
    assert "hint" not in public and public["question"] == "Q?"


def test_the_public_view_keeps_what_the_learner_needs_to_answer():
    questions = make_practice_sheet()["questions"]
    mcq = next(q for q in questions if q["type"] == "mcq")

    public = public_question(mcq)

    assert public["options"] == mcq["options"] and public["question"] == mcq["question"]
    numerical = public_question(next(q for q in questions if q["type"] == "numerical"))
    assert numerical["unit"] == "steps" and numerical["decimal_precision"] == 0 and "options" not in numerical
    msq = public_question({**BASE, "marks": 2, "type": "msq", **STORED["msq"]})
    assert msq["options"] == list("abcde")

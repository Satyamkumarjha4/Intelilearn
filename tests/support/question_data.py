"""Builders for stored test questions, made the way the graph makes them: a schema-valid `TestQuestion` (what a model
writes), then `QuestionFinisher` (marks from the table, the numerical answer computed)."""

from graph.questions import MarksPolicy, QuestionFinisher
from graph.schemas import TestQuestion


def written(kind: str, number: int, difficulty: str = "easy", **overrides) -> dict:
    """The question as a model writes it: no marks, no computed answer."""
    marks = MarksPolicy.marks(kind, difficulty)
    base = {
        "id": f"t{number}",
        "type": kind,
        "concept": f"Concept {number}",
        "difficulty": difficulty,
        "question": f"Question number {number} about binary search?",
    }
    extra = {
        "mcq": {"options": [f"Choice {c} {number}" for c in "ABCD"], "correct_index": 1},
        "msq": {"options": [f"Choice {c} {number}" for c in "ABCDE"], "correct_indices": [0, 2]},
        "numerical": {"answer_expr": "2 ** 2", "tolerance": 0.01, "decimal_precision": 0, "unit": "steps"},
        "short_answer": {
            "model_answer": "Halve the range.",
            "criteria": [{"text": "names halving", "marks": 1}, {"text": "says why it works", "marks": marks - 1}],
        },
        "long_answer": {
            "model_answer": "A full explanation.",
            "criteria": [
                {"text": "states the invariant", "marks": marks - 2},
                {"text": "shows why it holds", "marks": 1},
                {"text": "gives an example", "marks": 1},
            ],
        },
    }[kind]
    return TestQuestion(**(base | extra | overrides)).model_dump(mode="json")


def make_question(kind: str, number: int, difficulty: str = "easy", **overrides) -> dict:
    """The question as it is stored."""
    (question,), problems = QuestionFinisher().finish([written(kind, number, difficulty, **overrides)])
    assert not problems, problems
    return question

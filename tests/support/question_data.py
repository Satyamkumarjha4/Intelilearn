"""Builders for stored test questions, made the way the graph makes them: a schema-valid `TestQuestion` (what a model
writes), then `QuestionFinisher` (marks from the table, the numerical answer computed)."""

import json
import re

from graph.questions import MarksPolicy, QuestionFinisher
from graph.schemas import QuestionBatch, TestQuestion


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


class ScriptedQuestions:
    """Answers `test.generate` the way a model would: one question for each line of the prompt, in order. A question's
    text is its number, so none repeats. A spoiler is `(applies, change)`: the first time a call's cells satisfy
    `applies(cells)` (a list of (type, difficulty)) the answer is changed by `change(questions, questions_so_far)`."""

    LINE = re.compile(r"^\d+\. (\w+), (\w+), worth", re.M)
    ALLOWED = re.compile(r'^Allowed concepts \(copy one exactly into "concept"\): (\[.*\])$', re.M)

    def __init__(self):
        self.written = 0
        self.history = []
        self.spoilers = []

    def __call__(self, messages):
        cells = self.LINE.findall(messages[0].content)
        allowed = [json.loads(found) for found in self.ALLOWED.findall(messages[0].content + messages[1].content)]
        questions = []
        for kind, difficulty in cells:
            self.written += 1
            # A question about a lesson names one of the lesson's concepts, as the prompt asks; else a made-up one.
            concept = {"concept": allowed[0][self.written % len(allowed[0])]} if allowed else {}
            questions.append(written(kind, self.written, difficulty, **concept))
        spoiler = next((s for s in self.spoilers if s[0](cells)), None)
        if spoiler and "REJECTED" not in messages[1].content:
            self.spoilers.remove(spoiler)
            spoiler[1](questions, self.history)
        self.history += questions
        return QuestionBatch(questions=questions)

"""The kinds of question that exist."""

import math
import re
from typing import Any, ClassVar

from ..levels import MarkTier
from .base import QuestionType, Score
from .expressions import ExpressionError, ExpressionEvaluator


class McqType(QuestionType):
    key = "mcq"
    guidance = "exactly 4 different options and correct_index."
    own_public_fields = ("options",)
    solution_fields = ("correct_index",)
    marks = {MarkTier.NORMAL: 1, MarkTier.DIFFICULT: 2}

    def missing_fields(self, question: dict) -> list[str]:
        missing = []
        if not question.get("options") or len(question["options"]) != 4:
            missing.append("options (exactly 4)")
        index = question.get("correct_index")
        if index is None or not 0 <= index <= 3:
            missing.append("correct_index (0-3)")
        return missing

    def problems(self, question: dict, label: str) -> list[str]:
        from ..validators.base import TextRules  # imported here: validators import this package

        return TextRules.option_problems(label, question["options"])

    def score(self, question: dict, answer: Any) -> Score:
        right = isinstance(answer, int) and not isinstance(answer, bool) and answer == question["correct_index"]
        return Score.of(right, question["marks"])

    def expected_text(self, question: dict) -> str:
        return f'The correct answer is "{question["options"][question["correct_index"]]}".'


class MsqType(QuestionType):
    """Choose all that apply. Marked in whole marks, in the spec's order: nothing picked, or any wrong option, is 0; all
    the right ones is full marks; at least half of them is full minus 1; fewer is 1."""

    key = "msq"
    guidance = "4 to 6 different options and correct_indices (at least 2 of them are correct, not all)."
    own_public_fields = ("options",)
    solution_fields = ("correct_indices",)
    marks = {MarkTier.NORMAL: 2, MarkTier.DIFFICULT: 3}

    def missing_fields(self, question: dict) -> list[str]:
        missing = []
        options = question.get("options")
        if not isinstance(options, list) or not 4 <= len(options) <= 6:
            missing.append("options (4 to 6)")
        indices = question.get("correct_indices")
        valid = (
            isinstance(indices, list)
            and len(indices) >= 2
            and len(set(indices)) == len(indices)
            and all(type(i) is int and 0 <= i < len(options or []) for i in indices)
        )
        if not valid:
            missing.append("correct_indices (at least 2 different options)")
        return missing

    def problems(self, question: dict, label: str) -> list[str]:
        from ..validators.base import TextRules  # imported here: validators import this package

        return TextRules.option_problems(label, question["options"])

    def score(self, question: dict, answer: Any) -> Score:
        marks, correct = question["marks"], set(question["correct_indices"])
        chosen = self._chosen(answer)
        if chosen is None or not chosen or chosen - correct:
            return Score(False, 0)
        if chosen == correct:
            return Score(True, marks)
        return Score(False, marks - 1 if len(chosen) * 2 >= len(correct) else 1)

    @staticmethod
    def _chosen(answer: Any) -> set[int] | None:
        """The options picked, or None when the answer is not a list of whole numbers."""
        if not isinstance(answer, list) or not all(type(i) is int for i in answer):
            return None
        return set(answer)

    def expected_text(self, question: dict) -> str:
        names = [f'"{question["options"][i]}"' for i in question["correct_indices"]]
        return "The correct answers are " + (", ".join(names[:-1]) + " and " + names[-1]) + "."


class NumericalType(QuestionType):
    """The generator writes the answer as an expression (`answer_expr`); `QuestionFinisher` computes `answer` from it.
    `decimal_precision` rounds that answer and hints how many decimals to type; it never rejects an input."""

    key = "numerical"
    guidance = (
        "answer_expr (the answer as a maths expression: + - * / **, parentheses, pi, e, sqrt, sin, cos, tan, asin, "
        "acos, atan, log (base 10), ln, exp, abs; angles in radians), tolerance, decimal_precision (0-6), unit. "
        "Never type the final number yourself."
    )
    own_public_fields = ("unit", "decimal_precision")
    solution_fields = ("answer", "tolerance", "unit")
    marks = {MarkTier.NORMAL: 2, MarkTier.DIFFICULT: 3}

    #: a number, then optionally a unit: "4", "4.0", "-3e2", "4 steps"
    NUMBER: ClassVar[re.Pattern] = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([^\d\s.+-].*)?$")

    def missing_fields(self, question: dict) -> list[str]:
        missing = []
        if not isinstance(question.get("answer_expr"), str) or not question["answer_expr"].strip():
            missing.append("answer_expr")
        if question.get("tolerance") is None or question["tolerance"] < 0:
            missing.append("tolerance (>= 0)")
        precision = question.get("decimal_precision")
        if type(precision) is not int or not 0 <= precision <= 6:
            missing.append("decimal_precision (0-6)")
        return missing

    def problems(self, question: dict, label: str) -> list[str]:
        """The expression must still compute (a hand-edited or stale question), and its answer must be stored."""
        if not question.get("answer_expr"):
            return []  # a question from before expressions: it keeps the answer it was stored with
        try:
            ExpressionEvaluator().evaluate(question["answer_expr"])
        except ExpressionError as exc:
            return [f"{label}: the answer_expr cannot be computed: {exc}"]
        return [] if question.get("answer") is not None else [f"{label}: the answer was not computed."]

    def score(self, question: dict, answer: Any) -> Score:
        value = self.number(answer)
        right = (
            value is not None
            and math.isfinite(value)
            and abs(value - question["answer"]) <= (question["tolerance"] + 1e-9)
        )
        return Score.of(right, question["marks"])

    def number(self, answer: Any) -> float | None:
        """The number in a learner's answer (`4`, `4.0`, `4 steps`), or None."""
        if isinstance(answer, bool):
            return None
        if isinstance(answer, (int, float)):
            return float(answer)
        if isinstance(answer, str) and (match := self.NUMBER.match(answer)):
            return float(match.group(1))
        return None

    def expected_text(self, question: dict) -> str:
        unit = f" {question['unit']}" if question.get("unit") else ""
        return f"The expected answer is {question['answer']:g}{unit} (accepted within ±{question['tolerance']:g})."


class OpenEndedType(QuestionType):
    """A question only a judgement can mark, against criteria that each carry whole marks. When the topic is programming
    the answer may be code: the question then names its `language` (and may give `starter_code`), which the learner's
    editor needs; the criteria judge the code, which is read and never run."""

    auto_scored = False
    own_public_fields = ("language", "starter_code")
    solution_fields = ("model_answer", "criteria")

    def score(self, question: dict, answer: Any) -> Score:
        return Score.needs_judgement()

    def missing_fields(self, question: dict) -> list[str]:
        missing = []
        if not question.get("model_answer"):
            missing.append("model_answer")
        if not question.get("criteria"):
            missing.append("criteria")
        return missing

    def problems(self, question: dict, label: str) -> list[str]:
        criteria = question.get("criteria")
        if not criteria:  # a question from before criteria: `LegacyQuestionAdapter` derives them when read
            return []
        problems = []
        if any(not str(c.get("text", "")).strip() for c in criteria):
            problems.append(f"{label}: describe each criterion in words.")
        if any(type(c.get("marks")) is not int or c["marks"] < 1 for c in criteria):
            problems.append(f"{label}: each criterion is worth a whole number of marks, at least 1.")
        elif (total := sum(c["marks"] for c in criteria)) != question["marks"]:
            problems.append(
                f"{label}: the criteria are worth {total} marks together; the question is worth {question['marks']}."
            )
        return problems


class ShortAnswerType(OpenEndedType):
    key = "short_answer"
    guidance = (
        "model_answer and criteria (two or three, each a thing a good answer says; their marks add up to the "
        "question's)."
    )
    marks = {MarkTier.NORMAL: 2, MarkTier.DIFFICULT: 3}


class LongAnswerType(OpenEndedType):
    key = "long_answer"
    guidance = (
        "model_answer and criteria (three to five, each a thing a good answer does; their marks add up to the "
        "question's)."
    )
    marks = {MarkTier.NORMAL: 5, MarkTier.DIFFICULT: 6}


class CodeType(OpenEndedType):
    """Code questions of lessons written before the modular parts. New questions do not use it: code is a format of a
    short or long answer. `LegacyQuestionAdapter` reads the old ones."""

    key = "code"
    own_public_fields = ("language", "starter_code")
    solution_fields = ("model_answer", "reference_solution", "test_cases", "criteria")
    marks = None  # a legacy question keeps the marks it was stored with

    def missing_fields(self, question: dict) -> list[str]:
        missing = [name for name in ("language", "reference_solution") if not question.get(name)]
        if not question.get("test_cases"):
            missing.append("test_cases")
        return missing

    def problems(self, question: dict, label: str) -> list[str]:
        from ..validators.questions import QuestionRules  # imported here: validators import this package

        if (question.get("language") or "").lower() == "python" and question.get("reference_solution"):
            return QuestionRules.python_problems(f"{label} reference solution", question["reference_solution"])
        return []

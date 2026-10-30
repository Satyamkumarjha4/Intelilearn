"""The kinds of question that exist today."""

import math
import re
from typing import Any, ClassVar

from .base import QuestionType, Score


class McqType(QuestionType):
    key = "mcq"
    own_public_fields = ("options",)
    solution_fields = ("correct_index",)

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


class NumericalType(QuestionType):
    key = "numerical"
    own_public_fields = ("unit",)
    solution_fields = ("answer", "tolerance", "unit")

    #: a number, then optionally a unit: "4", "4.0", "-3e2", "4 steps"
    NUMBER: ClassVar[re.Pattern] = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([^\d\s.+-].*)?$")

    def missing_fields(self, question: dict) -> list[str]:
        missing = []
        if question.get("answer") is None:
            missing.append("answer")
        if question.get("tolerance") is None or question["tolerance"] < 0:
            missing.append("tolerance (>= 0)")
        return missing

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
    """A question only a judgement can mark."""

    auto_scored = False

    def score(self, question: dict, answer: Any) -> Score:
        return Score.needs_judgement()


class ShortAnswerType(OpenEndedType):
    key = "short_answer"
    solution_fields = ("model_answer", "key_points")

    def missing_fields(self, question: dict) -> list[str]:
        missing = []
        if not question.get("model_answer"):
            missing.append("model_answer")
        if not question.get("key_points"):
            missing.append("key_points")
        return missing


class LongAnswerType(OpenEndedType):
    key = "long_answer"
    solution_fields = ("model_answer", "rubric")

    def missing_fields(self, question: dict) -> list[str]:
        missing = []
        if not question.get("model_answer"):
            missing.append("model_answer")
        if not question.get("rubric"):
            missing.append("rubric")
        return missing


class CodeType(OpenEndedType):
    """Code questions of lessons written before the modular parts. New questions do not use it: they are short or long
    answers (`LegacyQuestionAdapter` reads the old ones)."""

    key = "code"
    own_public_fields = ("language", "starter_code")
    solution_fields = ("model_answer", "reference_solution", "test_cases")

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

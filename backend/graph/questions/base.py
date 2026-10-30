"""What a kind of question is: its fields, how its shape is checked, how an answer to it is marked.

One subclass per kind (Strategy), found by name in `QuestionTypes`. The flat Pydantic question model stays as the shape
a model writes (providers handle unions badly in structured output); these classes sit beside it and use its `type` to
look up behaviour, so a new kind is a new class and no `if kind ==` branch anywhere (docs/architecture/design.md §4.8).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from ..levels import MarkTier


@dataclass(frozen=True)
class Score:
    """How one answer was marked. `correct` is None when only a judgement (a model's) can mark it."""

    correct: bool | None
    awarded: int | None

    @classmethod
    def needs_judgement(cls) -> "Score":
        return cls(None, None)

    @classmethod
    def of(cls, correct: bool, marks: int) -> "Score":
        return cls(correct, marks if correct else 0)


class QuestionType(ABC):
    key: ClassVar[str]
    #: what a learner may see before answering, besides the fields every question has
    own_public_fields: ClassVar[tuple[str, ...]] = ()
    #: what the answer is made of: shown after the learner answered, never before
    solution_fields: ClassVar[tuple[str, ...]] = ()
    #: marked by the code (one right answer), or only by a judgement
    auto_scored: ClassVar[bool] = True
    #: what to tell a generator about writing this kind (the marks are added by `generator_guidance`)
    guidance: ClassVar[str] = ""
    #: what a new question is worth, by mark tier; None for a kind that new questions no longer use
    marks: ClassVar[dict[MarkTier, int] | None] = None

    COMMON_PUBLIC_FIELDS: ClassVar[tuple[str, ...]] = ("id", "type", "concept", "difficulty", "marks", "question")

    @property
    def public_fields(self) -> tuple[str, ...]:
        return self.COMMON_PUBLIC_FIELDS + self.own_public_fields

    def public(self, question: dict) -> dict:
        return {key: question.get(key) for key in self.public_fields if question.get(key) is not None}

    def solution(self, question: dict) -> dict:
        return {key: question[key] for key in self.solution_fields if question.get(key) is not None}

    def generator_guidance(self) -> str:
        """One line for a prompt: how to write this kind, and what it is worth."""
        normal, difficult = self.marks_for(MarkTier.NORMAL), self.marks_for(MarkTier.DIFFICULT)
        return f"{self.key}: {self.guidance} Worth {normal} (easy, basic, standard) or {difficult} (difficult, expert)."

    def marks_for(self, tier: MarkTier) -> int:
        if self.marks is None:
            raise LookupError(f"New {self.key} questions have no marks: a stored one keeps its own.")
        return self.marks[tier]

    @abstractmethod
    def missing_fields(self, question: dict) -> list[str]:
        """What a question of this kind is missing or has wrong, as short phrases ("options (exactly 4)")."""

    def problems(self, question: dict, label: str) -> list[str]:
        """Rules beyond the shape that need the whole question (distinct options, code that parses)."""
        return []

    @abstractmethod
    def score(self, question: dict, answer: Any) -> Score:
        """Mark `answer` against `question["marks"]`."""

    def expected_text(self, question: dict) -> str:
        """What a right answer is, in words, for feedback on a wrong one."""
        return ""

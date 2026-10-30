"""What a question is worth. The table is in the kinds of question (`QuestionType.marks`); this is how to ask."""

from typing import Any

from ..levels import Difficulty
from .registry import QuestionTypes, UnknownQuestionType


class MarksPolicy:
    """Marks come from here and nowhere else: never from a model, and never changed for a question already stored."""

    @staticmethod
    def marks(kind: str, difficulty: Any) -> int:
        """The marks of a new question of this kind and difficulty (an old difficulty name is read as the new one)."""
        tier = Difficulty.parse(difficulty).tier
        try:
            return QuestionTypes.get(kind).marks_for(tier)
        except UnknownQuestionType:
            raise ValueError(f"Unknown kind of question: {kind!r}") from None
        except LookupError as exc:
            raise ValueError(str(exc)) from None

"""Finds the `QuestionType` of a question by its `type`."""

from .base import QuestionType
from .types import CodeType, LongAnswerType, McqType, MsqType, NumericalType, ShortAnswerType


class UnknownQuestionType(KeyError):
    """No kind of question has that name."""


class QuestionTypes:
    _BY_KEY: dict[str, QuestionType] = {
        t.key: t for t in (McqType(), MsqType(), NumericalType(), ShortAnswerType(), LongAnswerType(), CodeType())
    }

    @classmethod
    def get(cls, key: str) -> QuestionType:
        try:
            return cls._BY_KEY[key]
        except KeyError:
            raise UnknownQuestionType(key) from None

    @classmethod
    def keys(cls) -> tuple[str, ...]:
        return tuple(cls._BY_KEY)

    @classmethod
    def guidance(cls, keys) -> str:
        """The generator's instructions for the kinds a prompt asks for, one line each."""
        return "\n".join(f"- {cls.get(key).generator_guidance()}" for key in keys)

    @classmethod
    def of(cls, question: dict) -> QuestionType:
        return cls.get(question["type"])

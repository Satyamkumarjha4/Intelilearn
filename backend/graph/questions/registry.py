"""Finds the `QuestionType` of a question by its `type`."""

from .base import QuestionType
from .presets import QuizPresets
from .traits import TopicTraits
from .types import CodeType, LongAnswerType, McqType, MsqType, NumericalType, ShortAnswerType


class UnknownQuestionType(KeyError):
    """No kind of question has that name."""


class QuestionTypes:
    _BY_KEY: dict[str, QuestionType] = {
        t.key: t for t in (McqType(), MsqType(), NumericalType(), ShortAnswerType(), LongAnswerType(), CodeType())
    }

    #: the kinds a new quiz can ask, in the order they are listed and dealt out (the legacy `code` is not one)
    OFFERED: tuple[str, ...] = ("mcq", "msq", "numerical", "short_answer", "long_answer")
    SUBJECTIVE: tuple[str, ...] = ("short_answer", "long_answer")

    @classmethod
    def for_topic(cls, traits: TopicTraits | None, count: int) -> tuple[str, ...]:
        """The kinds a quiz of `count` questions on a topic offers: choice questions always, numerical ones for a
        quantitative topic, short and long answers from ten questions. A topic nobody judged (`traits` is None) offers
        everything the count allows. The same rule is applied by the server and mirrored by the wizard."""
        if not QuizPresets.is_preset(count):
            raise ValueError(f"A quiz has 5, 10, 15, 20, 25 or 30 questions (a preset), got {count!r}")
        traits = traits or TopicTraits.everything()
        return tuple(
            kind
            for kind in cls.OFFERED
            if (kind != "numerical" or traits.quantitative)
            and (kind not in cls.SUBJECTIVE or count >= QuizPresets.SUBJECTIVE_FROM)
        )

    @classmethod
    def code_format(cls, traits: TopicTraits | None, types) -> bool:
        """Whether the answers to short and long questions may be code: a programming topic that has asked for them.
        Code is never assumed for a topic nobody judged."""
        return bool(traits and traits.programming and any(kind in cls.SUBJECTIVE for kind in types))

    @staticmethod
    def for_calibration() -> tuple[str, ...]:
        """The calibration walk is multiple choice, whatever the quiz asks for."""
        return ("mcq",)

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

"""The sizes a quick quiz can have (plan D17). Constants, not settings: changing them would make the wizard and the
attempts' comparison inconsistent."""

from typing import Any, ClassVar


class QuizPresets:
    COUNTS: ClassVar[tuple[int, ...]] = (5, 10, 15, 20, 25, 30)
    DEFAULT: ClassVar[int] = 10
    #: short and long answers need room to be marked fairly, so a quiz must have at least this many questions
    SUBJECTIVE_FROM: ClassVar[int] = 10

    @classmethod
    def is_preset(cls, count: Any) -> bool:
        return type(count) is int and count in cls.COUNTS

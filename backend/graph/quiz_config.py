"""What a quick quiz is asked to be, checked in one place (plan D17, §7.4, §8.5). Pure.

The settings are fixed when the quiz is made (changing them makes a new quiz), they decide what the model is asked to
write, and attempts at "the same quiz" are grouped by their hash. So the rules about the count, the kinds of question
and the level mode are one class: the server enforces it and the wizard mirrors it.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .levels import StarRating
from .questions import QuestionTypes
from .questions.presets import QuizPresets
from .questions.traits import TopicTraits

__all__ = ["QuizConfig", "QuizConfigError", "QuizPresets"]


class QuizConfigError(ValueError):
    """A setting the quiz cannot have. `field` is the request field it belongs to."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field, self.message = field, message


@dataclass(frozen=True)
class QuizConfig:
    num_questions: int
    types: tuple[str, ...]
    level_mode: str  # self_rating, calibration or existing_score
    self_rating_halves: int | None = None

    LEVEL_MODES = ("self_rating", "calibration", "existing_score")

    @classmethod
    def validate(
        cls,
        *,
        num_questions: Any,
        types: Sequence[Any],
        level: Any,
        traits: TopicTraits | None,
        source_type: str,
    ) -> "QuizConfig":
        """The config the request describes, or `QuizConfigError` naming the field that is wrong. `traits` is what is
        known of the topic (None: nobody judged it, so every kind the count allows is accepted)."""
        if not QuizPresets.is_preset(num_questions):
            raise QuizConfigError("num_questions", "A quiz has 5, 10, 15, 20, 25 or 30 questions.")
        kinds = cls._kinds(types, num_questions, traits)
        mode, halves = cls._level(level, source_type)
        return cls(num_questions, kinds, mode, halves)

    @classmethod
    def _kinds(cls, types: Sequence[Any], count: int, traits: TopicTraits | None) -> tuple[str, ...]:
        if not isinstance(types, (list, tuple)) or not types:
            raise QuizConfigError("types", "Pick at least one kind of question.")
        unknown = [str(kind) for kind in types if kind not in QuestionTypes.OFFERED]
        if unknown:
            raise QuizConfigError("types", f"Not a kind of question: {', '.join(unknown)}.")
        offered = QuestionTypes.for_topic(traits, count)
        refused = [kind for kind in types if kind not in offered]
        if refused:
            if any(kind in QuestionTypes.SUBJECTIVE for kind in refused) and count < QuizPresets.SUBJECTIVE_FROM:
                raise QuizConfigError(
                    "types", f"Short and long answers need a quiz of {QuizPresets.SUBJECTIVE_FROM} or more questions."
                )
            raise QuizConfigError("types", f"This topic does not have {', '.join(dict.fromkeys(refused))} questions.")
        return tuple(kind for kind in QuestionTypes.OFFERED if kind in types)

    @classmethod
    def _level(cls, level: Any, source_type: str) -> tuple[str, int | None]:
        if not isinstance(level, dict) or level.get("mode") not in cls.LEVEL_MODES:
            raise QuizConfigError("level", "Pick how to find your level: a self-rating, a calibration or your scores.")
        mode = level["mode"]
        if mode != "self_rating":
            if "rating" in level:
                raise QuizConfigError("level", "A rating goes with the self-rating mode.")
            if mode == "existing_score" and source_type != "lessons":
                raise QuizConfigError("level", "Your test scores can only set the level of a quiz made from lessons.")
            return mode, None
        try:
            return mode, StarRating.from_stars(level.get("rating")).halves
        except ValueError:
            raise QuizConfigError("level", "Rate yourself from 0.5 to 5 stars, in half steps.") from None

    @property
    def has_subjective(self) -> bool:
        return any(kind in QuestionTypes.SUBJECTIVE for kind in self.types)

    @property
    def capped(self) -> bool:
        """Whether the per-batch cap on short and long answers applies: not when only those were picked."""
        from .questions import BatchPlanner

        return BatchPlanner.cap_applies(self.types)

    def hash(self, source_type: str, keys: Sequence[str]) -> str:
        """The same settings give the same hash, however the topic is spelled or the lessons and kinds are ordered, so
        attempts at the same quiz can be grouped."""
        if source_type == "topic":
            ordered = [" ".join(" ".join(keys).split()).casefold()]
        else:
            ordered = sorted(str(key) for key in keys)
        canonical = json.dumps(
            {"source_type": source_type, "keys": ordered, **self.as_dict()}, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def as_dict(self) -> dict:
        return {
            "num_questions": self.num_questions,
            "types": list(self.types),
            "level_mode": self.level_mode,
            "self_rating_halves": self.self_rating_halves,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QuizConfig":
        """A config that was stored. It is checked again, but its topic is not judged (that was done when it was"
        " made)."""
        mode = data.get("level_mode")
        halves = data.get("self_rating_halves")
        if mode not in cls.LEVEL_MODES or (mode == "self_rating") != (halves is not None):
            raise ValueError("Not a stored quiz config: the level")
        if mode == "self_rating":
            StarRating(halves)
        count, types = data.get("num_questions"), data.get("types")
        if not QuizPresets.is_preset(count):
            raise ValueError("Not a stored quiz config: the question count is not a preset")
        if not isinstance(types, list) or not types or any(kind not in QuestionTypes.OFFERED for kind in types):
            raise ValueError("Not a stored quiz config: the kinds of question")
        return cls(count, tuple(types), mode, halves)

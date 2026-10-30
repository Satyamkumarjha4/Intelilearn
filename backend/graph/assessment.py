"""Assessment sources (Strategy): the ways a learner's starting point is found.

Every source produces the one `LearnerAssessment` document, stamped with the level scheme and with `source`, so what
comes after (the level gate, the plan, the pages) does not care where the level came from. Follow-ups, the calibration
quiz and a quiz result arrive in later phases as new classes and one line in `AssessmentSources`
(docs/architecture/design.md §4.20).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from .levels import Level, LevelScheme, StarRating
from .shapes import LessonShapes
from .validators import AssessmentGuard


@dataclass(frozen=True)
class AssessmentRequest:
    """What a source may need. Each source reads its own part and refuses a request that lacks it."""

    draft: dict | None = None  # what the model wrote (the diagnostic)
    prerequisites_to_cover: list[dict] = field(default_factory=list)  # found by the prerequisite quiz
    mastery_choice: str | None = None  # "lesson" when the learner who aced the quiz chose the Expert lesson
    self_rating_halves: int | None = None


class AssessmentSource(ABC):
    key: ClassVar[str]
    #: whether `assess` finishes the answer of a model (the node calls the model first) or needs none
    uses_model: ClassVar[bool]

    @abstractmethod
    def assess(self, request: AssessmentRequest) -> dict:
        """The stored assessment: a new dict, the request is not changed."""

    @staticmethod
    def stamped(assessment: dict, source: str) -> dict:
        return LevelScheme.stamp({**assessment, "source": source})


class DiagnosticSource(AssessmentSource):
    """The model's assessment of the quiz results, made safe: the quiz decides the prerequisites, and a learner who
    aced the quiz and chose the Expert lesson is an Expert."""

    key = "diagnostic"
    uses_model = True

    def __init__(self, guard: AssessmentGuard | None = None):
        self.guard = guard or AssessmentGuard()

    def assess(self, request: AssessmentRequest) -> dict:
        if request.draft is None:
            raise ValueError("The diagnostic source needs the model's draft of the assessment.")
        assessment = self.guard.apply(request.draft, request.prerequisites_to_cover)
        if request.mastery_choice == "lesson":
            assessment["level"] = Level.EXPERT.value
        return self.stamped(assessment, self.key)


class SelfRatingSource(AssessmentSource):
    """The learner's own rating, with nothing tested: the level of the stars, the level's own starting point and notes,
    and low confidence."""

    key = "self_rating"
    uses_model = False

    def assess(self, request: AssessmentRequest) -> dict:
        if request.self_rating_halves is None:
            raise ValueError("The self-rating source needs the learner's rating.")
        level = StarRating(request.self_rating_halves).level()
        shape = LessonShapes.for_level(level)
        assessment = {
            "level": level.value,
            "known_concepts": [],
            "gaps": [],
            "prerequisites_to_cover": [],
            "start_point": shape.start_point,
            "author_notes": shape.author_notes,
            "confidence": "low",
        }
        return self.stamped(assessment, self.key)


class AssessmentSources:
    _SOURCES: ClassVar[tuple[AssessmentSource, ...]] = (DiagnosticSource(), SelfRatingSource())

    @classmethod
    def for_key(cls, key: str) -> AssessmentSource:
        for source in cls._SOURCES:
            if source.key == key:
                return source
        raise KeyError(f"No assessment source {key!r}; known: {', '.join(cls.keys())}")

    @classmethod
    def keys(cls) -> tuple[str, ...]:
        return tuple(source.key for source in cls._SOURCES)

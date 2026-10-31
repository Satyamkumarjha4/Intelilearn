"""Assessment sources (Strategy): the ways a learner's starting point is found.

Every source produces the one `LearnerAssessment` document, stamped with the level scheme and with `source`, so what
comes after (the level gate, the plan, the pages) does not care where the level came from. A new way to find a level is
one new class and one line in `AssessmentSources` (docs/architecture/design.md §4.20, §4.23): the calibration walk and
the two score sources arrived with the quick quiz.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from .followups import FollowupTargets
from .ladder import AdaptiveLadder
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
    followup_level: str | None = None  # foundation or advanced, for a lesson made from a test result
    walk: list[bool] | None = None  # the calibration quiz: right (True) or wrong for each of its five questions
    base_level: str | None = None  # a score moves this level: a lesson's own, or the level a quiz was written at
    band: str | None = None  # how the score went: fail, normal or excellent
    known_concepts: list[str] = field(default_factory=list)  # what a score showed they know
    weak_concepts: list[str] = field(default_factory=list)  # what it showed they do not (the gaps)


class AssessmentSource(ABC):
    key: ClassVar[str]
    #: whether `assess` finishes the answer of a model (the node calls the model first) or needs none
    uses_model: ClassVar[bool]
    #: what the lesson records as the place its level came from (`Lesson.level_source`)
    level_source: ClassVar[str]

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
    level_source = "diagnostic"

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
    level_source = "self_rating"

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


class FollowupSource(AssessmentSource):
    """A lesson made from a test result: the level is fixed by what the follow-up is for (`FollowupTargets`), not asked
    of the learner and not found by a quiz. Nothing is known about their concepts: the follow-up uses the overall score
    only (spec 3.4), so it has no known concepts and no gaps, the level's own starting point and notes, and low
    confidence."""

    key = "followup"
    uses_model = False
    level_source = "test_score"

    def assess(self, request: AssessmentRequest) -> dict:
        if request.followup_level is None:
            raise ValueError("The follow-up source needs the follow-up level.")
        level = FollowupTargets.level_for(request.followup_level)
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


class BandShift:
    """A score moves a level one step (decision D7): an excellent one up, a fail down, a normal one not at all, and
    never past Beginner or Expert. A 90% on a Beginner lesson does not make someone an Expert in the topic."""

    SHIFTS = {"excellent": 1, "normal": 0, "fail": -1}

    @classmethod
    def of(cls, level: Level, band: str | None) -> Level:
        if band not in cls.SHIFTS:
            raise ValueError(f"Not a score band: {band!r}; it is fail, normal or excellent.")
        return level.shifted(cls.SHIFTS[band])


class ScoredAssessment(AssessmentSource):
    """The shared shape of the sources that read a level off a score: the level moves by the band, and the weak concepts
    are the gaps. Nothing is asked of a model."""

    uses_model = False

    def assess(self, request: AssessmentRequest) -> dict:
        if request.base_level is None:
            raise ValueError(f"The {self.key} source needs the level the score is moved from.")
        level = BandShift.of(Level.parse(request.base_level), request.band)
        return self.document(level, request.known_concepts, request.weak_concepts, "medium")

    def document(self, level: Level, known: list[str], gaps: list[str], confidence: str) -> dict:
        shape = LessonShapes.for_level(level)
        assessment = {
            "level": level.value,
            "known_concepts": list(known),
            "gaps": list(gaps),
            "prerequisites_to_cover": [],
            "start_point": shape.start_point,
            "author_notes": shape.author_notes,
            "confidence": confidence,
        }
        return self.stamped(assessment, self.key)


class CalibrationSource(ScoredAssessment):
    """The level at the end of the calibration walk (`AdaptiveLadder`): five multiple-choice questions, no concepts."""

    key = "calibration"
    level_source = "calibration"

    def assess(self, request: AssessmentRequest) -> dict:
        if request.walk is None:
            raise ValueError("The calibration source needs the learner's walk.")
        return self.document(AdaptiveLadder().level(list(request.walk)), [], [], "medium")


class TestScoreSource(ScoredAssessment):
    """A lesson test the learner already took (D7): the lesson's own level, moved by how the latest graded attempt went,
    and the concepts it told them to revisit as the gaps."""

    __test__ = False  # not a pytest test class, whatever its name looks like

    key = "test_score"
    level_source = "test_score"


class QuizResultSource(ScoredAssessment):
    """A quick quiz the learner finished: the level it was written at, moved by how it went, with what it showed as
    known and as gaps. A lesson made from the result is written from this."""

    key = "quiz_result"
    level_source = "quiz_result"


class AssessmentSources:
    _SOURCES: ClassVar[tuple[AssessmentSource, ...]] = (
        DiagnosticSource(),
        SelfRatingSource(),
        FollowupSource(),
        CalibrationSource(),
        TestScoreSource(),
        QuizResultSource(),
    )

    @classmethod
    def for_key(cls, key: str) -> AssessmentSource:
        for source in cls._SOURCES:
            if source.key == key:
                return source
        raise KeyError(f"No assessment source {key!r}; known: {', '.join(cls.keys())}")

    @classmethod
    def keys(cls) -> tuple[str, ...]:
        return tuple(source.key for source in cls._SOURCES)

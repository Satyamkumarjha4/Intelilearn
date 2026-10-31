"""Where a quick quiz's questions come from: a topic, or lessons the learner has made (plan D18).

`QuizSources` finds the lessons a request names (only the caller's own, and only ones with pages), works out each
lesson's level for the quiz, and shares the questions between them. It decides nothing about the model: the summaries
the question writer is given are built later, in the graph, from each lesson's plan.
"""

from dataclasses import dataclass

from rest_framework.exceptions import NotFound, ValidationError

from graph.assessment import AssessmentRequest, AssessmentSources
from graph.levels import Level
from graph.quiz_config import QuizConfig
from graph.quiz_sources import SourceSplit, SourceSplitError
from graph.scoring import ScoreBand, Thresholds
from lessons.models import Intent, Lesson, Stage, TestSubmission

from .errors import SourceNotUsable


@dataclass(frozen=True)
class SourceRow:
    """One lesson's part of a quiz: the level its questions are written at and how many of them there are."""

    lesson: Lesson
    level: Level
    share: int


class QuizTitle:
    """The name of a quiz made from lessons, built from their topics."""

    MAX = 200

    @classmethod
    def of(cls, topics: list[str]) -> str:
        first = topics[0].strip()
        title = first if len(topics) == 1 else f"{first} + {len(topics) - 1} more"
        return title[: cls.MAX]


class QuizSources:
    def __init__(self, split: SourceSplit | None = None):
        self.split = split

    def lessons(self, user, lesson_ids: list, *, max_lessons: int) -> list[Lesson]:
        """The caller's lessons, in the order asked. Another learner's lesson is as missing as one that does not"
        " exist."""
        if not lesson_ids:
            raise ValidationError({"source": ["Pick at least one lesson."]})
        if len(set(lesson_ids)) != len(lesson_ids):
            raise ValidationError({"source": ["Each lesson can be picked once."]})
        if len(lesson_ids) > max_lessons:
            raise ValidationError({"source": [f"A quiz can combine at most {max_lessons} lessons."]})
        found = {lesson.pk: lesson for lesson in Lesson.objects.owned_by(user).filter(pk__in=lesson_ids)}
        if len(found) != len(lesson_ids):
            raise NotFound()
        lessons = [found[lesson_id] for lesson_id in lesson_ids]
        for lesson in lessons:
            self.require_usable(lesson)
        return lessons

    @staticmethod
    def require_usable(lesson: Lesson) -> None:
        """Only a lesson with pages can be asked about: a lesson that is only study sheets has none, and a lesson still
        being built has no plan yet (decision 1 of the 9.5 report)."""
        if lesson.intent != Intent.LESSON or lesson.sheets_only:
            raise SourceNotUsable(
                f"“{lesson.topic}” is study sheets only, so there is nothing to ask about.", lesson_id=lesson.pk
            )
        if lesson.stage != Stage.READY or not lesson.plan or not lesson.pages:
            raise SourceNotUsable(f"“{lesson.topic}” is not ready yet.", lesson_id=lesson.pk)

    def rows(self, lessons: list[Lesson], config: QuizConfig, *, max_lessons: int) -> list[SourceRow]:
        """Each lesson's level and share. With the learner's scores as the level mode, a lesson's level is its own moved
        by how its latest test went; with a rating or a calibration the one level the learner chose applies to every
        lesson, so each row keeps the lesson's own level for display."""
        split = self.split or SourceSplit(max_lessons)
        try:
            shares = split.shares(config.num_questions, [(str(lesson.pk), lesson.created_at) for lesson in lessons])
        except SourceSplitError as exc:
            raise ValidationError({"num_questions" if "questions" in str(exc) else "source": [str(exc)]}) from exc
        levels = self.levels(lessons, config)
        return [SourceRow(lesson, levels[lesson.pk], shares[str(lesson.pk)]) for lesson in lessons]

    def levels(self, lessons: list[Lesson], config: QuizConfig) -> dict:
        if config.level_mode != "existing_score":
            return {lesson.pk: Level.parse(lesson.level) for lesson in lessons}
        return {lesson.pk: self.level_from_score(lesson) for lesson in lessons}

    def level_from_score(self, lesson: Lesson) -> Level:
        """The lesson's level moved by its latest graded attempt (D7). A lesson with none has no score to use."""
        attempt = (
            TestSubmission.objects.filter(lesson=lesson, status=TestSubmission.Status.GRADED, available__gt=0)
            .order_by("-attempt_no")
            .first()
        )
        if attempt is None:
            raise ValidationError({"level": [f"“{lesson.topic}” has no graded test yet, so there is no score to use."]})
        band = attempt.band or ScoreBand.of(attempt.awarded, attempt.available, Thresholds()).value
        request = AssessmentRequest(base_level=lesson.level, band=band)
        return Level.parse(AssessmentSources.for_key("test_score").assess(request)["level"])

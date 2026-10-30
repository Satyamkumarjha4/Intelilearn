"""Lesson stages and the moves between them (State pattern), kept free of the ORM so they are easy to test."""

from django.db import models


class Stage(models.TextChoices):
    PREPARING_DIAGNOSTIC = "preparing_diagnostic", "Preparing the diagnostic"
    AWAITING_DIAGNOSTIC = "awaiting_diagnostic", "Waiting for diagnostic answers"
    AWAITING_PREREQUISITE = "awaiting_prerequisite", "Waiting for prerequisite answers"
    AWAITING_CHOICE = "awaiting_choice", "Waiting for a study-sheet choice"
    GENERATING_MATERIAL = "generating_material", "Writing the study sheet"
    GENERATING_LESSON = "generating_lesson", "Building the lesson"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class Route(models.TextChoices):
    PREREQUISITE = "prerequisite", "Prerequisites first"
    LESSON = "lesson", "Lesson"
    MASTERY = "mastery", "Mastery"


class Entry(models.TextChoices):
    """How the learner's starting level was found. A follow-up and a quiz result arrive in later phases."""

    DIAGNOSTIC = "diagnostic", "Quick check"
    SELF_RATING = "self_rating", "Self-rating"
    FOLLOWUP = "followup", "Follow-up"
    QUIZ_RESULT = "quiz_result", "Quiz result"


class Intent(models.TextChoices):
    """What the learner asked for. Only a lesson can be asked for until study sheets from a topic arrive."""

    LESSON = "lesson", "A lesson"
    SHEETS = "sheets", "Study sheets"


class Origin(models.TextChoices):
    """Why the lesson was made: set by the server and verified, never taken from the client's word."""

    DIRECT = "direct", "Direct"
    RECOMMENDATION = "recommendation", "Recommended by a result"
    FOLLOWUP = "followup", "Follow-up"
    QUIZ_RESULT = "quiz_result", "Quiz result"


class LevelSource(models.TextChoices):
    """Where `Lesson.level` came from."""

    DIAGNOSTIC = "diagnostic", "Quick check"
    SELF_RATING = "self_rating", "Self-rating"
    TEST_SCORE = "test_score", "Test score"
    QUIZ_RESULT = "quiz_result", "Quiz result"


class FollowupLevel(models.TextChoices):
    """What a follow-up lesson is for: the basics a failed test points back to, or the next step after an excellent
    one."""

    FOUNDATION = "foundation", "Foundation"
    ADVANCED = "advanced", "Advanced"


class MasteryOptions(models.TextChoices):
    """What the learner who aced the quick check was shown. A lesson already waiting at the choice when the Expert
    lesson was added keeps the three sheets it was offered; the choice published since offers the lesson or the two
    sheets."""

    THREE_SHEETS = "three_sheets", "Three sheets"
    LESSON_OR_SHEETS = "lesson_or_sheets", "The Expert lesson or two sheets"


class MaterialKind(models.TextChoices):
    CHEAT_SHEET = "cheat_sheet", "Cheat sheet"
    REVISION_SHEET = "revision_sheet", "Revision sheet"
    PRACTICE_SHEET = "practice_sheet", "Practice sheet"


class IllegalTransition(ValueError):
    """The lesson cannot move from one stage to the other."""


class StageTransitions:
    """Only legal moves happen: a finished lesson never goes back to a quiz.

    Leaving `failed` is how a retry resumes: it goes back to the stage of the node that gave up, or, after the learner
    pressed Stop, to the stage the lesson was in (`StopPoint`), which can be a quiz it is waiting on.
    """

    TABLE: dict[Stage, frozenset[Stage]] = {
        # a self-rated lesson has no quiz, so it goes straight to building the lesson
        Stage.PREPARING_DIAGNOSTIC: frozenset({Stage.AWAITING_DIAGNOSTIC, Stage.GENERATING_LESSON, Stage.FAILED}),
        Stage.AWAITING_DIAGNOSTIC: frozenset(
            {Stage.AWAITING_PREREQUISITE, Stage.AWAITING_CHOICE, Stage.GENERATING_LESSON, Stage.FAILED}
        ),
        Stage.AWAITING_PREREQUISITE: frozenset({Stage.GENERATING_LESSON, Stage.FAILED}),
        # the Expert lesson or the sheets (two sheets are written at once, and the lesson says so when it starts)
        Stage.AWAITING_CHOICE: frozenset({Stage.GENERATING_LESSON, Stage.GENERATING_MATERIAL, Stage.FAILED}),
        Stage.GENERATING_MATERIAL: frozenset({Stage.READY, Stage.FAILED}),
        Stage.GENERATING_LESSON: frozenset({Stage.READY, Stage.FAILED}),
        Stage.READY: frozenset(),
        Stage.FAILED: frozenset(
            {
                Stage.PREPARING_DIAGNOSTIC,
                Stage.AWAITING_DIAGNOSTIC,
                Stage.AWAITING_PREREQUISITE,
                Stage.AWAITING_CHOICE,
                Stage.GENERATING_LESSON,
                Stage.GENERATING_MATERIAL,
            }
        ),
    }

    def allowed(self, source: str, target: str) -> bool:
        return source == target or Stage(target) in self.TABLE[Stage(source)]

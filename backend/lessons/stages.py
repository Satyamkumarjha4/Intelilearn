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
        Stage.PREPARING_DIAGNOSTIC: frozenset({Stage.AWAITING_DIAGNOSTIC, Stage.FAILED}),
        Stage.AWAITING_DIAGNOSTIC: frozenset(
            {Stage.AWAITING_PREREQUISITE, Stage.AWAITING_CHOICE, Stage.GENERATING_LESSON, Stage.FAILED}
        ),
        Stage.AWAITING_PREREQUISITE: frozenset({Stage.GENERATING_LESSON, Stage.FAILED}),
        Stage.AWAITING_CHOICE: frozenset({Stage.GENERATING_MATERIAL, Stage.FAILED}),
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

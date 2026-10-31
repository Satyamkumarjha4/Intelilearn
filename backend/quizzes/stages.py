"""Quick quiz stages and the moves between them (State pattern), kept free of the ORM so they are easy to test."""

from typing import ClassVar

from django.db import models

from lessons.stages import IllegalTransition  # noqa: F401  (a quiz refuses a move with the lessons' error)


class QuizStage(models.TextChoices):
    PREPARING = "preparing", "Preparing the quiz"
    AWAITING_CALIBRATION = "awaiting_calibration", "Waiting for the calibration answers"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class QuizStageTransitions:
    """Only legal moves happen. A ready quiz never moves on: a retake leaves it ready while its questions are written,
    and
    a retake that fails does not fail the quiz. A failed quiz is over (it is deleted and made again)."""

    #: the stages in which the quiz is still being made
    MAKING: ClassVar[tuple[QuizStage, ...]] = (QuizStage.PREPARING, QuizStage.AWAITING_CALIBRATION)

    TABLE: ClassVar[dict[QuizStage, frozenset[QuizStage]]] = {
        # the calibration walk pauses the quiz; when it is over the questions are written, so it is preparing again
        QuizStage.PREPARING: frozenset({QuizStage.AWAITING_CALIBRATION, QuizStage.READY, QuizStage.FAILED}),
        QuizStage.AWAITING_CALIBRATION: frozenset({QuizStage.PREPARING, QuizStage.FAILED}),
        QuizStage.READY: frozenset(),
        QuizStage.FAILED: frozenset(),
    }

    def allowed(self, source: str, target: str) -> bool:
        return source == target or QuizStage(target) in self.TABLE[QuizStage(source)]

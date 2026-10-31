"""Unit under test: `quizzes.stages.QuizStageTransitions`, the table of legal moves between the stages of a quick quiz.

Why: the stage decides which screen the learner sees (building, calibration, the quiz itself) and which API calls are
allowed. A move the table wrongly allows (a ready quiz back to calibration) shows the wrong screen; one it wrongly
refuses strands a quiz. A quiz that is ready stays usable whatever happens to a later retake, so it never fails.

Use cases:
- the documented moves are allowed: preparing to calibration (the walk), to ready (a quiz that needs none) or to failed;
  calibration back to preparing (the walk is over and the questions are being written) or to failed
- every other move is refused, including any move out of ready and out of failed
- staying in the same stage is always allowed (a node that runs again)
- the stages a learner can still act in are the ones that are not ready or failed
"""

import itertools

import pytest

from quizzes.stages import QuizStage, QuizStageTransitions

ALLOWED = {
    (QuizStage.PREPARING, QuizStage.AWAITING_CALIBRATION),
    (QuizStage.PREPARING, QuizStage.READY),
    (QuizStage.PREPARING, QuizStage.FAILED),
    (QuizStage.AWAITING_CALIBRATION, QuizStage.PREPARING),
    (QuizStage.AWAITING_CALIBRATION, QuizStage.FAILED),
}


@pytest.mark.parametrize(("source", "target"), list(itertools.product(QuizStage, QuizStage)))
def test_a_move_is_allowed_exactly_when_the_table_says_so(source, target):
    expected = source == target or (source, target) in ALLOWED

    assert QuizStageTransitions().allowed(source, target) is expected


def test_a_ready_quiz_never_moves_on():
    assert not any(QuizStageTransitions().allowed(QuizStage.READY, other) for other in QuizStage if other != "ready")


def test_a_failed_quiz_is_over():
    assert not any(QuizStageTransitions().allowed(QuizStage.FAILED, other) for other in QuizStage if other != "failed")


def test_the_stages_a_quiz_is_still_being_made_in():
    assert QuizStageTransitions.MAKING == (QuizStage.PREPARING, QuizStage.AWAITING_CALIBRATION)

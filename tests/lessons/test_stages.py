"""Unit under test: `lessons.stages.StageTransitions`, the table of legal moves between lesson stages.

Why: the stage decides which screen the learner sees and which API calls are allowed. A move the table wrongly
allows (a finished lesson back to a quiz) shows the wrong screen; one it wrongly refuses strands a lesson.

Use cases:
- the documented moves are allowed, including a stopped lesson going back to the quiz stage it was in
- every other move is refused
- staying in the same stage is always allowed (a node that re-runs on retry)
"""

import pytest

from lessons.stages import Stage, StageTransitions


class TestStageTransitions:
    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (Stage.PREPARING_DIAGNOSTIC, Stage.AWAITING_DIAGNOSTIC),
            (Stage.AWAITING_DIAGNOSTIC, Stage.AWAITING_PREREQUISITE),
            (Stage.AWAITING_DIAGNOSTIC, Stage.AWAITING_CHOICE),
            (Stage.AWAITING_DIAGNOSTIC, Stage.GENERATING_LESSON),
            (Stage.AWAITING_PREREQUISITE, Stage.GENERATING_LESSON),
            (Stage.AWAITING_CHOICE, Stage.GENERATING_MATERIAL),
            (Stage.GENERATING_MATERIAL, Stage.READY),
            (Stage.GENERATING_LESSON, Stage.READY),
            (Stage.GENERATING_LESSON, Stage.FAILED),
            (Stage.PREPARING_DIAGNOSTIC, Stage.FAILED),
            (Stage.FAILED, Stage.PREPARING_DIAGNOSTIC),
            (Stage.FAILED, Stage.GENERATING_LESSON),
            (Stage.FAILED, Stage.GENERATING_MATERIAL),
            (Stage.FAILED, Stage.AWAITING_DIAGNOSTIC),  # a stopped lesson goes back to where it was
            (Stage.FAILED, Stage.AWAITING_PREREQUISITE),
            (Stage.FAILED, Stage.AWAITING_CHOICE),
        ],
        ids=lambda s: str(s.value),
    )
    def test_allows_the_documented_moves(self, source, target):
        assert StageTransitions().allowed(source, target) is True

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (Stage.READY, Stage.AWAITING_DIAGNOSTIC),
            (Stage.READY, Stage.FAILED),
            (Stage.AWAITING_DIAGNOSTIC, Stage.READY),
            (Stage.PREPARING_DIAGNOSTIC, Stage.GENERATING_LESSON),
            (Stage.AWAITING_PREREQUISITE, Stage.AWAITING_DIAGNOSTIC),
            (Stage.FAILED, Stage.READY),
            (Stage.GENERATING_LESSON, Stage.AWAITING_DIAGNOSTIC),
        ],
        ids=lambda s: str(s.value),
    )
    def test_refuses_everything_else(self, source, target):
        assert StageTransitions().allowed(source, target) is False

    @pytest.mark.parametrize("stage", list(Stage), ids=lambda s: str(s.value))
    def test_staying_in_the_same_stage_is_always_allowed(self, stage):
        assert StageTransitions().allowed(stage, stage) is True

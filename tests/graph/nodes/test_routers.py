"""Unit under test: `graph.nodes.routers.CheckRouter` and `LevelRouter`, the conditional edges after a validator and
after the diagnostic is graded.

Why: they decide whether a bad model output is retried, accepted or ends the run, and which path a learner takes after
the diagnostic. A wrong edge loops forever or sends a master through a beginner's lesson.

Use cases:
- a valid output goes on
- an invalid output is retried while attempts remain
- an invalid output with the error set (attempts spent) goes to the failure node
- the level router sends each route to its configured destination
"""

import pytest

from graph.nodes.routers import CheckRouter, LevelRouter

router = CheckRouter("diagnostic", ok="publish", retry="generate", fail="mark_failed")


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"feedback": {"diagnostic": []}}, "publish"),
        ({}, "publish"),
        ({"feedback": {"other": ["problem"]}}, "publish"),
        ({"feedback": {"diagnostic": ["too few questions"]}}, "generate"),
        ({"feedback": {"diagnostic": ["too few questions"]}, "error": "gave up"}, "mark_failed"),
    ],
    ids=["valid", "no-feedback-yet", "other-keys-ignored", "retry", "attempts-spent"],
)
def test_check_router_goes_on_retries_or_fails(state, expected):
    assert router(state) == expected


def test_level_router_sends_each_route_to_its_destination():
    level = LevelRouter({"mastery": "m", "prerequisite": "p", "lesson": "l"})

    assert [level({"route": r}) for r in ("mastery", "prerequisite", "lesson")] == ["m", "p", "l"]

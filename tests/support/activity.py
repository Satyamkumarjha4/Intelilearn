"""Activity sinks for tests (see lessons/activity.py): one that counts, one that raises.

- `CountingActivity`: records each `record` call (user, kind, instant), so a test can say how many times and when.
- `RaisingActivity`: counts the call, then fails, to show that a broken sink cannot undo a learner's submission.
"""

from datetime import datetime
from typing import Any

from lessons.activity import ActivityKind


class CountingActivity:
    def __init__(self):
        self.recorded: list[tuple[Any, ActivityKind, datetime]] = []

    def record(self, user, kind: ActivityKind, at: datetime) -> None:
        self.recorded.append((user, kind, at))

    @property
    def kinds(self) -> list[str]:
        return [str(kind) for _, kind, _ in self.recorded]


class RaisingActivity(CountingActivity):
    def record(self, user, kind: ActivityKind, at: datetime) -> None:
        super().record(user, kind, at)
        raise RuntimeError("the sink is broken")

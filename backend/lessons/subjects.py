"""What a graph run belongs to. Today that is always a `Lesson`; a quick quiz joins in phase 9.6.

The runner, `StopPoint`, `RunEffects`, `LessonService.cancel` and the console reach the owner of a run through
`GraphRun.subject`, and only through the members below, so a second kind of subject needs no change in them.
"""

from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class RunSubject(Protocol):
    id: UUID
    owner_id: UUID
    stage: str  # for StopPoint and the progress screen
    error: str  # why it failed, when a stage says it did
    config_snapshot: dict
    settings_snapshot: dict

    def fail(self, error: str) -> None: ...

    def record(self, **fields) -> None: ...

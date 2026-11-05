"""The seam that lets a later feature learn when a learner studied, without `lessons` knowing why it wants to know.

A daily credit and a streak (credits plan T16) are earned by real study: a metered action that succeeded, or an attempt
that was handed in. The services that seal an attempt report it here, at the instant it was sealed, and the sink decides
what that is worth. The default sink (`NullActivity`) does nothing, so the app behaves as if this did not exist. It is
chosen by the `ACTIVITY_SINK` setting the way `ACTION_GATE` chooses the gate.

What counts: an attempt that was sealed with at least one real answer. An attempt of only blank answers (Phase 9's
blank-attempt rule: stored, scores 0, no offer) does not, nor does one that was refused, failed or only started, so
a request that learns nothing cannot earn anything.
"""

import logging
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class ActivityKind(StrEnum):
    """What the learner did. Not a price: the sink maps it to whatever it rewards."""

    TEST_ATTEMPT = "test_attempt"  # a lesson's test handed in
    QUIZ_ATTEMPT = "quiz_attempt"  # a quick quiz handed in
    QUICK_CHECK = "quick_check"  # a Quick check, or the Basics check that follows it, handed in
    METERED_ACTION = "metered_action"  # an action the gate charged for was done (reported by the gate, not a service)


class ActivitySink(Protocol):
    def record(self, user: Any, kind: ActivityKind, at: datetime) -> None:
        """The learner did `kind` at the instant `at`. Once per sealed attempt; a sink must cope with a repeat."""
        ...


class NullActivity:
    """The default: nothing is recorded."""

    def record(self, user: Any, kind: ActivityKind, at: datetime) -> None:
        pass


class GuardedActivity:
    """What the services hold: a sink whose failure is logged and kept to itself. The attempt is already sealed when it
    is called, and a learner's answers are worth more than a credit, so a broken sink must never turn a result into an
    error."""

    def __init__(self, sink: ActivitySink):
        self.sink = sink

    def record(self, user: Any, kind: ActivityKind, at: datetime) -> None:
        try:
            self.sink.record(user, kind, at)
        except Exception:
            logger.exception("Could not record %s activity for user %s", kind, getattr(user, "pk", user))


class ActivitySinks:
    @staticmethod
    def configured() -> ActivitySink:
        """The sink named by the `ACTIVITY_SINK` setting, as `ACTION_GATE` names the gate."""
        return import_string(settings.ACTIVITY_SINK)()

    @classmethod
    def guarded(cls, sink: ActivitySink | None = None) -> GuardedActivity:
        return GuardedActivity(sink or cls.configured())

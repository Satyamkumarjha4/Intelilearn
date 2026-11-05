"""The only source of "now" in `credits` (credits plan T15). Everything that depends on the time (an expiry, a window, a
day boundary) takes a `Clock`, so a test moves the time instead of waiting for it."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current instant, timezone-aware."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

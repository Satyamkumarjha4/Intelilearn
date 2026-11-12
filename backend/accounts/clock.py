"""The one source of "now" for the sign-in code (phase 11, T10): a port, so a test moves time instead of waiting for it.

`credits` has its own `Clock`; `accounts` cannot import it (the dependency runs from `credits` to `accounts`), so
this is
the same two-line port. A fake that has `now()` satisfies both.
"""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

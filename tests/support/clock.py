"""A clock for tests of the credits app (see credits/clock.py): time stands still until the test moves it.

`credits` has no other source of "now", so a test that needs an expiry, a window or a day boundary sets the clock and
never sleeps.
"""

from datetime import UTC, datetime, timedelta


class FakeClock:
    def __init__(self, start: datetime | None = None):
        self.current = start or datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def set(self, instant: datetime) -> "FakeClock":
        self.current = instant
        return self

    def advance(self, **delta) -> "FakeClock":
        """Move forward by a `timedelta`'s keywords: `clock.advance(days=30)`."""
        self.current += timedelta(**delta)
        return self

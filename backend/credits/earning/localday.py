"""A calendar day in a learner's time zone (credits plan T15).

The daily credit and the streak belong to the learner's day, not the server's: an Indian learner's day changes at
18:30 UTC.
The day is found with the system's zone database, so it follows daylight saving (a day is 23 or 25 hours long twice a
year).
Pure: an instant and a zone name in, a date out. "Today" comes from an injected `Clock`.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..clock import Clock


@dataclass(frozen=True)
class LocalDay:
    date: date
    zone: str

    @staticmethod
    def zone_info(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError) as error:
            raise ValueError(f"{name!r} is not a time zone.") from error

    @classmethod
    def of(cls, instant: datetime, zone: str) -> "LocalDay":
        """The day `instant` falls in, in `zone`."""
        return cls(instant.astimezone(cls.zone_info(zone)).date(), zone)

    @classmethod
    def today(cls, clock: Clock, zone: str) -> "LocalDay":
        return cls.of(clock.now(), zone)

    def next_midnight(self) -> datetime:
        """The first instant of the next day, in UTC. Follows the real length of the day."""
        midnight = datetime.combine(self.date + timedelta(days=1), time.min, tzinfo=self.zone_info(self.zone))
        return midnight.astimezone(UTC)

    def before(self, days: int = 1) -> date:
        return self.date - timedelta(days=days)

    def after(self, days: int = 1) -> date:
        return self.date + timedelta(days=days)

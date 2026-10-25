"""The ranges the console's pages offer: today, the last 7 days, the last 30 days (Value Object + a small registry).

A range ends now and starts at midnight, so "7d" is today and the six days before it. The *previous* period is the
same length and ends where the range starts, which is what a delta ("12 more lessons than before") compares against.
Days are in the project's time zone (UTC), the same one `TruncDate` groups the daily chart by.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone


@dataclass(frozen=True)
class Period:
    key: str
    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime
    chart_days: int

    def chart_dates(self) -> list[date]:
        """The days of the daily chart, oldest first, ending with the day `end` falls on."""
        last = timezone.localtime(self.end).date()
        return [last - timedelta(days=offset) for offset in range(self.chart_days - 1, -1, -1)]


class Periods:
    #: range key → (days it covers, days its chart shows)
    RANGES = {"today": (1, 14), "7d": (7, 14), "30d": (30, 30)}

    def of(self, key: str, now: datetime | None = None) -> Period:
        if key not in self.RANGES:
            raise ValueError(f"Unknown range {key!r}; choose one of: {', '.join(self.RANGES)}")
        days, chart_days = self.RANGES[key]
        now = now or timezone.now()
        midnight = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        start = midnight - timedelta(days=days - 1)
        return Period(key, start, now, start - timedelta(days=days), start, chart_days)

    MAX_CUSTOM_DAYS = 366

    def custom(self, first: date, last: date, now: datetime | None = None) -> Period:
        """Whole days from `first` to `last`, both included: from midnight of the first to the end of the last (or now,
        if that has not come yet). The previous period is the equally long one before it."""
        days = (last - first).days + 1
        if not 1 <= days <= self.MAX_CUSTOM_DAYS:
            raise ValueError(f"A custom range runs from 1 to {self.MAX_CUSTOM_DAYS} days, in order (got {days}).")
        now = now or timezone.now()
        zone = timezone.get_current_timezone()
        start = datetime.combine(first, time.min, tzinfo=zone)
        end = min(datetime.combine(last + timedelta(days=1), time.min, tzinfo=zone), now)
        length = timedelta(days=days)
        return Period("custom", start, end, start - length, start, min(days, self.MAX_CUSTOM_DAYS))

    def keys(self) -> list[str]:
        return list(self.RANGES)

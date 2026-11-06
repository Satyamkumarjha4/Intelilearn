"""When a purchase's periods run (credits plan T19, spec §5.2 and §5.3). Pure: instants in, instants out.

One plan is active at a time, so a purchase starts when the learner's last period ends (or now, if nothing is
running), and
several periods of one purchase follow one another with no gap and no overlap. How many periods may be open at once is
limited."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from .errors import QueueFull


@dataclass(frozen=True)
class PeriodSpan:
    position: int
    starts_at: datetime
    ends_at: datetime
    credits: int


class PlanChain:
    def periods(
        self,
        *,
        last_end: datetime | None,
        now: datetime,
        period_days: int,
        credits: int,
        quantity: int,
        open_periods: int = 0,
        limit: int | None = 12,
    ) -> list[PeriodSpan]:
        """The periods a purchase of `quantity` makes. `last_end` is when the learner's last open period ends (None for
        none); `open_periods` counts the periods open now. Raises `QueueFull` if they would pass `limit` (None: no
        limit)."""
        if quantity < 1 or period_days < 1:
            raise ValueError("A purchase makes at least one period of at least a day.")
        if limit is not None and open_periods + quantity > limit:
            raise QueueFull(open_periods, limit)
        length = timedelta(days=period_days)
        start = last_end if last_end is not None and last_end > now else now
        spans = []
        for position in range(1, quantity + 1):
            spans.append(PeriodSpan(position, start, start + length, credits))
            start += length
        return spans

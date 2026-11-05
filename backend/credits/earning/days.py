"""A learner's streak days in the database: the truth about a streak, and the cache of what they add up to."""

from datetime import date

from django.db import transaction

from ..clock import Clock, SystemClock
from ..models import StreakDay, StreakState
from .streak import StreakCalculator, StreakSnapshot


class StreakDays:
    def __init__(self, clock: Clock | None = None, calculator: StreakCalculator | None = None):
        self.clock = clock or SystemClock()
        self.calculator = calculator or StreakCalculator()

    def dates(self, user) -> set[date]:
        return set(StreakDay.objects.filter(user=user).values_list("local_date", flat=True))

    def repaired_on(self, user) -> list[date]:
        """The days each repair was made, for the limits."""
        return list(
            StreakDay.objects.filter(user=user, repaired_on__isnull=False).values_list("repaired_on", flat=True)
        )

    def add_active(self, user, day: date) -> bool:
        """Write the day if it is new. → whether it was (the first activity of a day earns the day's credit)."""
        _, created = StreakDay.objects.get_or_create(
            user=user, local_date=day, defaults={"kind": StreakDay.Kind.ACTIVE, "created_at": self.clock.now()}
        )
        return created

    def add_repaired(self, user, day: date, made_on: date) -> StreakDay:
        return StreakDay.objects.create(
            user=user, local_date=day, kind=StreakDay.Kind.REPAIRED, repaired_on=made_on, created_at=self.clock.now()
        )

    def snapshot(self, user, today: date) -> StreakSnapshot:
        return self.calculator.snapshot(self.dates(user), today)

    def refresh(self, user, snapshot: StreakSnapshot) -> StreakState:
        """Bring the cached state in line with the days. Nothing decides anything from it."""
        with transaction.atomic():
            state, _ = StreakState.objects.update_or_create(
                user=user,
                defaults={
                    "current_streak": snapshot.current,
                    "longest_streak": snapshot.longest,
                    "run_started_on": snapshot.run_started_on,
                    "last_day": snapshot.last_day,
                    "updated_at": self.clock.now(),
                },
            )
        return state

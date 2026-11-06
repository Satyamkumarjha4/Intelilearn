"""Telling a learner that credits are about to run out (credits plan §5.10).

Computed on every read from the live buckets and each one's source, in the learner's own days; nothing is stored, so a
notice can never be stale or disagree with the wallet. How early each kind of credit is announced is a
`NoticePolicy` (Strategy): a week of Pro is short and is announced late, a purchase is long and is announced twice.
Credits that lapse on the same local day are one message however many parcels they are. Signup, admin and refund
credits are never announced.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .clock import Clock, SystemClock
from .earning.localday import LocalDay
from .earning.zone import LearnerZone
from .models import CreditBucket, CreditSettings
from .refusals import credits_word

Source = CreditBucket.Source


@dataclass(frozen=True)
class NoticeBucket:
    """What a notice needs to know about a parcel of credits. `plan_key` is the plan a subscription parcel came from."""

    source: str
    remaining: int
    expires_at: datetime | None
    plan_key: str = ""


@dataclass(frozen=True)
class ExpiryNotice:
    id: str  # one per local day, so a browser can keep "dismissed today" for it
    expires_on: date  # the last day the credits can be used
    days_left: int  # 0 is the last day
    credits: int
    text: str

    def as_json(self) -> dict:
        return {
            "id": self.id, "expires_on": self.expires_on, "days_left": self.days_left, "credits": self.credits,
            "text": self.text,
        }  # fmt: skip


class NoticePolicy(ABC):
    """When, counted in days left, credits of one kind are announced. Template Method: the base class settles what holds
    for all of them (a lapsed parcel is never announced), a subclass says where its window is."""

    def shows(self, days_left: int, settings: CreditSettings) -> bool:
        return days_left >= 0 and self.in_window(days_left, settings)

    @abstractmethod
    def in_window(self, days_left: int, settings: CreditSettings) -> bool: ...


class NeverAnnounced(NoticePolicy):
    def in_window(self, days_left: int, settings: CreditSettings) -> bool:
        return False


class WeeklyWindow(NoticePolicy):
    """A week of Pro: from 2 days before the end, every day, to the last."""

    def in_window(self, days_left: int, settings: CreditSettings) -> bool:
        return days_left <= settings.weekly_notice_days


class MonthlyWindow(NoticePolicy):
    """Monthly Pro and Pro Plus: the last 7 days."""

    def in_window(self, days_left: int, settings: CreditSettings) -> bool:
        return days_left <= settings.monthly_notice_days


class BonusWindow(NoticePolicy):
    """Daily and streak credits: the last 7 days."""

    def in_window(self, days_left: int, settings: CreditSettings) -> bool:
        return days_left <= settings.bonus_notice_days


class PurchasedWindow(NoticePolicy):
    """Bought credits last a year: told once at 30 days left (for 3 days), then again in the last 7."""

    def in_window(self, days_left: int, settings: CreditSettings) -> bool:
        first = settings.purchased_notice_days
        in_first = first - settings.purchased_notice_show_days < days_left <= first
        return in_first or days_left <= settings.purchased_final_notice_days


class NoticePolicies:
    """The registry: the policy of each source, and of each plan a subscription parcel can come from. A kind of credit
    this does not know is never announced."""

    BY_SOURCE: dict[str, NoticePolicy] = {
        Source.DAILY: BonusWindow(),
        Source.WEEKLY_STREAK: BonusWindow(),
        Source.MONTHLY_STREAK: BonusWindow(),
        Source.PURCHASE: PurchasedWindow(),
    }
    BY_PLAN: dict[str, NoticePolicy] = {
        "weekly_pro": WeeklyWindow(),
        "monthly_pro": MonthlyWindow(),
        "pro_plus": MonthlyWindow(),
    }
    NEVER = NeverAnnounced()

    @classmethod
    def of(cls, bucket: NoticeBucket) -> NoticePolicy:
        if bucket.source == Source.SUBSCRIPTION:
            return cls.BY_PLAN.get(bucket.plan_key, cls.NEVER)
        return cls.BY_SOURCE.get(bucket.source, cls.NEVER)


class NoticeWords:
    """A notice as a learner reads it."""

    @staticmethod
    def of(days_left: int, credits: int, day: date) -> str:
        count = credits_word(credits)
        if days_left == 0:
            return f"This is your last day to use {count}."
        if days_left == 1:
            return f"{count} will run out tomorrow."
        return f"{count} will run out on {day:%A} {day.day} {day:%B}."


class ExpiryNotices:
    def __init__(self, clock: Clock | None = None):
        self.clock = clock or SystemClock()

    def for_user(self, user) -> list[ExpiryNotice]:
        """The notices to show this learner now, soonest first."""
        now = self.clock.now()
        live = CreditBucket.objects.filter(user=user, revoked_at__isnull=True, amount_remaining__gt=0)
        live = live.filter(expires_at__gt=now).select_related("period__purchase__plan")
        return self.of([self._bucket(row) for row in live], now, LearnerZone.of(user), CreditSettings.load())

    def count(self, user) -> int:
        return len(self.for_user(user))

    def of(
        self, buckets: Sequence[NoticeBucket], now: datetime, zone: str, settings: CreditSettings
    ) -> list[ExpiryNotice]:
        """Pure: the notices for these parcels, in this zone, at this moment."""
        today = LocalDay.of(now, zone).date
        days: dict[date, list[NoticeBucket]] = {}
        for bucket in buckets:
            if bucket.expires_at is not None and bucket.expires_at > now:
                days.setdefault(self._last_day(bucket.expires_at, zone), []).append(bucket)
        found = []
        for last_day, parcels in sorted(days.items()):
            days_left = (last_day - today).days
            if any(NoticePolicies.of(parcel).shows(days_left, settings) for parcel in parcels):
                total = sum(parcel.remaining for parcel in parcels)
                found.append(
                    ExpiryNotice(
                        f"expiry-{last_day.isoformat()}",
                        last_day,
                        days_left,
                        total,
                        NoticeWords.of(days_left, total, last_day),
                    )  # fmt: skip
                )
        return found

    @staticmethod
    def _last_day(expires_at: datetime, zone: str) -> date:
        """The last day the credits can be used: a parcel that lapses at local midnight lapses the day before."""
        return LocalDay.of(expires_at - timedelta(microseconds=1), zone).date

    @staticmethod
    def _bucket(row: CreditBucket) -> NoticeBucket:
        period = getattr(row, "period", None)
        plan_key = period.purchase.plan.key if period is not None else ""
        return NoticeBucket(row.source, row.amount_remaining, row.expires_at, plan_key)

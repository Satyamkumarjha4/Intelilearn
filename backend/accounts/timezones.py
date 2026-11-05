"""The learner's time zone: which names are real, and the rule for changing one.

The learner's day, for the daily credit and the streak, is the day in their zone (credits plan D9, T15). The zone is
taken from the browser at sign-up, so the first value is free. Changing it later is allowed once every 30 days, so that
hopping between zones cannot earn two days out of one real day. Code that needs the zone reads
`Profile.effective_timezone`; code that sets it goes through `ProfileTimezone`.
"""

import zoneinfo
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, ClassVar

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException


class TimezoneLocked(APIException):
    """A change inside the 30 days after the last one. `extra.locked_until` says when the next is allowed."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "timezone_locked"
    default_detail = "You changed your time zone recently. You can change it again once 30 days have passed."

    def __init__(self, locked_until: datetime):
        super().__init__()
        self.extra = {"locked_until": locked_until.isoformat()}


class TimeZoneNames:
    """The IANA names the system knows (`zoneinfo`), including the old spellings browsers still report."""

    DEFAULT: ClassVar[str] = "Asia/Kolkata"
    MAX_LENGTH: ClassVar[int] = 64
    _known: ClassVar[frozenset[str] | None] = None

    @classmethod
    def is_valid(cls, name: Any) -> bool:
        if not isinstance(name, str) or not name or name != name.strip():
            return False
        if cls._known is None:
            cls._known = frozenset(zoneinfo.available_timezones())
        return name in cls._known

    @classmethod
    def effective(cls, stored: str) -> str:
        """The zone in force: the learner's own, or the default for one who never set it."""
        return stored or cls.DEFAULT


class ProfileTimezone:
    LOCK = timedelta(days=30)

    def __init__(self, now: Callable[[], datetime] = timezone.now):
        self.now = now

    def locked_until(self, profile) -> datetime | None:
        """When the next change is allowed, or None when one is allowed now."""
        if profile.timezone_changed_at is None:
            return None
        until = profile.timezone_changed_at + self.LOCK
        return until if until > self.now() else None

    def apply(self, profile, name: str) -> None:
        """Set the zone on the profile (the caller saves). The first value is free; the same value again is nothing;
        any other change is refused inside the lock and otherwise starts a new one. `name` must already be valid."""
        if name == profile.timezone:
            return
        if profile.timezone:
            if (until := self.locked_until(profile)) is not None:
                raise TimezoneLocked(until)
            profile.timezone_changed_at = self.now()
        profile.timezone = name

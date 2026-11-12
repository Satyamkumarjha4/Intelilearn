"""The numbers of the verification codes, read from settings (the environment) when used, never written down here."""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings


@dataclass(frozen=True)
class VerificationSettings:
    code_digits: int = 6
    code_ttl: timedelta = timedelta(minutes=10)
    max_attempts: int = 5
    lock_strikes: int = 3
    lock_window: timedelta = timedelta(minutes=60)
    pending_ttl: timedelta = timedelta(hours=24)
    ticket_ttl: timedelta = timedelta(hours=24)

    @classmethod
    def from_settings(cls) -> "VerificationSettings":
        return cls(
            code_digits=settings.AUTH_CODE_DIGITS,
            code_ttl=timedelta(minutes=settings.AUTH_CODE_TTL_MINUTES),
            max_attempts=settings.AUTH_CODE_MAX_ATTEMPTS,
            lock_strikes=settings.AUTH_LOCK_STRIKES,
            lock_window=timedelta(minutes=settings.AUTH_LOCK_MINUTES),
            pending_ttl=timedelta(hours=settings.PENDING_SIGNUP_HOURS),
            ticket_ttl=timedelta(minutes=settings.SIGNUP_TICKET_MINUTES),
        )

    @property
    def code_minutes(self) -> int:
        return int(self.code_ttl.total_seconds() // 60)

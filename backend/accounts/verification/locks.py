"""Emails whose codes keep dying (plan 5.6): three dead codes within an hour lock the address for an hour.

The key is the canonical email **whether or not an account has it**, so a lock cannot be used to find accounts. The lock
is a row, so the console can show it and clear it."""

from django.db import transaction

from ..clock import Clock, SystemClock
from ..models import EmailLock
from .config import VerificationSettings


class EmailLocks:
    def __init__(self, clock: Clock | None = None, settings: VerificationSettings | None = None):
        self.clock = clock or SystemClock()
        self._settings = settings

    @property
    def settings(self) -> VerificationSettings:
        return self._settings or VerificationSettings.from_settings()

    def is_locked(self, email_canonical: str) -> bool:
        until = EmailLock.objects.filter(email_canonical=email_canonical).values_list("locked_until", flat=True).first()
        return until is not None and until > self.clock.now()

    def strike(self, email_canonical: str) -> None:
        """A code for this email just died. Strikes older than the window are forgotten; enough of them lock it."""
        now, config = self.clock.now(), self.settings
        with transaction.atomic():
            lock, _ = EmailLock.objects.select_for_update().get_or_create(
                email_canonical=email_canonical, defaults={"updated_at": now}
            )
            if lock.updated_at < now - config.lock_window:
                lock.strikes = 0
            lock.strikes += 1
            lock.updated_at = now
            if lock.strikes >= config.lock_strikes:
                lock.locked_until = now + config.lock_window
            lock.save()

    def clear(self, email_canonical: str) -> None:
        EmailLock.objects.filter(email_canonical=email_canonical).delete()

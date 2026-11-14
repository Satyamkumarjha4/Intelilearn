"""Where and how each account was made (`SignupRecord`): the one place that writes it, and the one that reads it for a
single learner (the console's panel). The abuse board's counters read the same rows (`AbuseCounters`)."""

from ..clock import Clock, SystemClock
from ..models import SignupRecord, User


class SignupRecords:
    def __init__(self, clock: Clock | None = None):
        self.clock = clock or SystemClock()

    def record(self, user: User, ip: str | None, method: str) -> SignupRecord:
        return SignupRecord.objects.create(
            user=user,
            ip=ip or None,
            email_domain=user.email_canonical.rpartition("@")[2],
            method=method,
            created_at=self.clock.now(),
        )

    @staticmethod
    def of(user: User) -> SignupRecord | None:
        """How this account was made, if the record is still kept (30 days)."""
        return SignupRecord.objects.filter(user=user).first()

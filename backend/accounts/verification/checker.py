"""Checking a code (plan 5.6, T9).

**The try is counted in the database before the code is compared**, with an `UPDATE ... WHERE attempts < max` that
changes a row only if a try was left: five simultaneous wrong guesses spend five tries, not one, and a sixth never
gets to compare. Every failure looks the same to the caller (`ok` false, no reason): a wrong code, an expired one, a
used one, a dead one, a locked email and an email nobody asked a code for are not told apart.
"""

from dataclasses import dataclass

from django.db.models import F

from ..clock import Clock, SystemClock
from ..models import VerificationCode
from .hasher import CodeHasher
from .locks import EmailLocks


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    row: VerificationCode | None = None  # the code that was consumed, only when `ok`


class CodeChecker:
    FAILED = CheckResult(False)

    def __init__(self, hasher: CodeHasher | None = None, locks: EmailLocks | None = None, clock: Clock | None = None):
        self.clock = clock or SystemClock()
        self.hasher = hasher or CodeHasher()
        self.locks = locks or EmailLocks(self.clock)

    def check(self, purpose: str, email_canonical: str, code: str) -> CheckResult:
        """Counts one try against the live code and, if `code` is right, consumes it. Call it so that its writes are
        kept when the answer is no (do not roll the transaction back on a failure: the counted try must stay)."""
        now = self.clock.now()
        if self.locks.is_locked(email_canonical):
            return self.FAILED
        row = VerificationCode.objects.filter(
            purpose=purpose, email_canonical=email_canonical, consumed_at__isnull=True,
            invalidated_at__isnull=True, expires_at__gt=now,
        ).first()  # fmt: skip
        if row is None:
            return self.FAILED
        counted = VerificationCode.objects.filter(
            pk=row.pk, attempts__lt=F("max_attempts"), consumed_at__isnull=True, invalidated_at__isnull=True
        ).update(attempts=F("attempts") + 1)
        if not counted:
            return self.FAILED  # no tries left: the code is dead
        if not self.hasher.matches(code, row.code_hash, purpose, email_canonical, row.pk):
            self._after_a_wrong_try(row, now)
            return self.FAILED
        used = VerificationCode.objects.filter(pk=row.pk, consumed_at__isnull=True, invalidated_at__isnull=True).update(
            consumed_at=now
        )
        return CheckResult(True, row) if used else self.FAILED  # another request used it first

    def _after_a_wrong_try(self, row: VerificationCode, now) -> None:
        attempts = VerificationCode.objects.filter(pk=row.pk).values_list("attempts", flat=True).first() or 0
        if attempts < row.max_attempts:
            return
        killed = VerificationCode.objects.filter(
            pk=row.pk, invalidated_at__isnull=True, consumed_at__isnull=True
        ).update(invalidated_at=now)
        if killed:  # only the request that killed it counts the strike, so simultaneous guesses do not count it twice
            self.locks.strike(row.email_canonical)

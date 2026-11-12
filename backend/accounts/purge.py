"""The daily housekeeping of the sign-in tables (`accounts.purge` on beat): personal data is kept only as long as
it is needed (plan T13)."""

from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import Q

from .clock import Clock, SystemClock
from .models import OutboundMail, PendingSignup, SignupRecord, VerificationCode


@dataclass(frozen=True)
class PurgeReport:
    mail: int = 0  # mail log rows deleted
    pending: int = 0  # sign-ups that never got their code, and their codes
    codes: int = 0  # spent, dead or expired codes
    signup_records: int = 0  # where-from records of accounts

    def as_dict(self) -> dict:
        return asdict(self)


class AccountsPurge:
    def __init__(self, clock: Clock | None = None):
        self.clock = clock or SystemClock()

    def run(self) -> PurgeReport:
        now = self.clock.now()
        spent_before = now - timedelta(days=settings.CODE_LOG_RETENTION_DAYS)
        old_mail = OutboundMail.objects.filter(created_at__lt=now - timedelta(days=settings.MAIL_LOG_RETENTION_DAYS))
        old_records = SignupRecord.objects.filter(
            created_at__lt=now - timedelta(days=settings.SIGNUP_RECORD_RETENTION_DAYS)
        )
        spent_codes = VerificationCode.objects.filter(
            Q(consumed_at__lt=spent_before) | Q(invalidated_at__lt=spent_before) | Q(expires_at__lt=spent_before)
        )
        return PurgeReport(
            mail=self._delete(old_mail),
            pending=self._delete(PendingSignup.objects.filter(expires_at__lt=now)),  # its codes go with it
            codes=self._delete(spent_codes),
            signup_records=self._delete(old_records),
        )

    @staticmethod
    def _delete(rows) -> int:
        """Deletes `rows` and counts only them, not what hangs on them and goes too."""
        return rows.delete()[1].get(rows.model._meta.label, 0)

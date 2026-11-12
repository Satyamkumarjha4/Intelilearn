"""The daily housekeeping of the sign-in tables (`accounts.purge` on beat): personal data is kept only as long as
it is needed."""

from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings

from .clock import Clock, SystemClock
from .models import OutboundMail


@dataclass(frozen=True)
class PurgeReport:
    mail: int = 0  # mail log rows deleted

    def as_dict(self) -> dict:
        return asdict(self)


class AccountsPurge:
    def __init__(self, clock: Clock | None = None):
        self.clock = clock or SystemClock()

    def run(self) -> PurgeReport:
        cutoff = self.clock.now() - timedelta(days=settings.MAIL_LOG_RETENTION_DAYS)
        deleted, _ = OutboundMail.objects.filter(created_at__lt=cutoff).delete()
        return PurgeReport(mail=deleted)

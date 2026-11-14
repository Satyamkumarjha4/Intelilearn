"""Writing the events the abuse board counts that have no account to hang on (`AuthEvent`).

Only the visitor's address and the email's **domain** are kept, never the address itself: the board answers "where do
the throwaway sign-ups and the failed guesses come from", not "who". A failure to write one never stops the request
that caused it."""

import logging

from ..clock import Clock, SystemClock
from ..models import AuthEvent

logger = logging.getLogger(__name__)


class AuthEvents:
    def __init__(self, clock: Clock | None = None):
        self.clock = clock or SystemClock()

    def record(self, kind: str, ip: str | None = None, email: str = "") -> None:
        domain = email.strip().rpartition("@")[2].lower() if "@" in email else ""
        try:
            AuthEvent.objects.create(kind=kind, ip=ip or None, email_domain=domain[:255], created_at=self.clock.now())
        except Exception:  # a counter must never take down the request it counts
            logger.exception("could not record an auth event")

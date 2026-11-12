"""The development backend: the message goes to the log, so a developer reads the code in `make logs`.

A printed code is a credential, so this backend refuses to run unless DJANGO_DEBUG is on (and the system check says
so at
start-up, `accounts.E001`).
"""

import logging

from django.conf import settings

from .mailer import Mailer, MailMessage, PermanentMailError, SendResult
from .registry import MailBackends

logger = logging.getLogger(__name__)


@MailBackends.register
class ConsoleMailer(Mailer):
    key = "console"

    def send(self, message: MailMessage) -> SendResult:
        if not settings.DEBUG:
            raise PermanentMailError("The console mail backend only runs with DJANGO_DEBUG=true.")
        logger.info("MAIL to %s [%s] %s\n%s", message.to, message.kind, message.subject, message.text)
        return SendResult("console")

    @classmethod
    def from_settings(cls) -> "ConsoleMailer":
        return cls()

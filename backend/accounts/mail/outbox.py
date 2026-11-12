"""The throwaway-stack backend: the mail log row keeps the text, so a browser test can read the code (T17, D5).

It runs only with MAIL_ALLOW_OUTBOX on **and** DJANGO_DEBUG on, and the system checks refuse the switch otherwise
(`accounts.E002`, `E003`): a readable outbox in production would hand a sign-up code to anyone who could read it.
"""

from django.conf import settings

from .mailer import Mailer, MailMessage, PermanentMailError, SendResult
from .registry import MailBackends


@MailBackends.register
class OutboxMailer(Mailer):
    key = "outbox"
    keeps_body = True

    def send(self, message: MailMessage) -> SendResult:
        if not (settings.DEBUG and settings.MAIL_ALLOW_OUTBOX):
            raise PermanentMailError("The outbox mail backend only runs on the throwaway test stack.")
        return SendResult("outbox")

    @classmethod
    def from_settings(cls) -> "OutboxMailer":
        return cls()

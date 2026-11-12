"""Sending mail without making a request wait for it (phase 11, T3).

`MailQueue.send` writes the log row and, once the transaction commits, hands the message to the Celery task
`accounts.send_mail`;
`MailDelivery` does the work. The message passes through the broker (it holds the code for a few seconds) and is
never stored
on the row, never logged and never returned as the task's result. Delivery is at least once, so a delivery that
finds its row
already sent does nothing.
"""

import logging
from collections.abc import Callable
from enum import Enum

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils.module_loading import import_string

from ..clock import Clock, SystemClock
from ..models import OutboundMail
from .mailer import MailMessage, PermanentMailError, TransientMailError
from .registry import MailBackends

logger = logging.getLogger(__name__)


class Outcome(Enum):
    SENT = "sent"
    RETRY = "retry"
    FAILED = "failed"
    SKIPPED = "skipped"  # already sent or failed, or the row was purged


class CeleryDispatch:
    """The production way a queued message is sent: hand it to the Celery task."""

    def __call__(self, row_id: int, payload: dict) -> object:
        return send_mail.delay(row_id, payload)


class MailQueue:
    """Logs a message and queues it for the task, after the surrounding transaction commits (a request that rolls back
    sends nothing). `MAIL_DISPATCH` names how it is handed on; tests swap it."""

    def __init__(self, dispatch: Callable[[int, dict], object] | None = None):
        self._dispatch = dispatch or import_string(settings.MAIL_DISPATCH)()

    def send(self, message: MailMessage) -> OutboundMail:
        row = OutboundMail.objects.create(
            kind=message.kind, to_email=message.to, subject=message.subject, backend=settings.MAIL_BACKEND
        )
        payload = message.as_payload()
        transaction.on_commit(lambda: self._dispatch(row.pk, payload))
        return row


class MailDelivery:
    MAX_ATTEMPTS = 5
    ERROR_LENGTH = 255

    def __init__(self, backends: MailBackends | None = None, clock: Clock | None = None):
        self.backends = backends or MailBackends()
        self.clock = clock or SystemClock()

    def deliver(self, outbound_id: int, payload: dict) -> Outcome:
        claimed = OutboundMail.objects.filter(pk=outbound_id, status=OutboundMail.Status.QUEUED).update(
            attempts=F("attempts") + 1
        )
        if not claimed:
            return Outcome.SKIPPED
        row = OutboundMail.objects.get(pk=outbound_id)
        message = MailMessage.from_payload(payload)
        try:
            mailer = self.backends.current()
            result = mailer.send(message)
        except TransientMailError as error:
            last = row.attempts >= self.MAX_ATTEMPTS
            self._record(row, OutboundMail.Status.FAILED if last else OutboundMail.Status.QUEUED, str(error))
            return Outcome.FAILED if last else Outcome.RETRY
        except PermanentMailError as error:
            self._record(row, OutboundMail.Status.FAILED, str(error))
            return Outcome.FAILED
        except Exception as error:  # a bug or a misconfiguration: say what kind, never what the message held
            logger.error("Mail %s failed unexpectedly: %s", row.pk, type(error).__name__)
            self._record(row, OutboundMail.Status.FAILED, type(error).__name__)
            return Outcome.FAILED
        row.status, row.error = OutboundMail.Status.SENT, ""
        row.sent_at, row.provider_message_id = self.clock.now(), result.message_id[:200]
        row.body_text = message.text if mailer.keeps_body else ""
        row.save(update_fields=["status", "error", "sent_at", "provider_message_id", "body_text"])
        return Outcome.SENT

    def _record(self, row: OutboundMail, status: str, reason: str) -> None:
        row.status, row.error = status, reason[: self.ERROR_LENGTH]
        row.save(update_fields=["status", "error"])


@shared_task(name="accounts.send_mail", bind=True, max_retries=MailDelivery.MAX_ATTEMPTS)
def send_mail(self, outbound_id: int, payload: dict) -> str:
    """Sends one queued email. Retries with a growing wait while the provider is busy; the log row says how it ended."""
    outcome = MailDelivery().deliver(outbound_id, payload)
    if outcome is Outcome.RETRY:
        raise self.retry(countdown=min(30 * 2**self.request.retries, 900))
    return outcome.value

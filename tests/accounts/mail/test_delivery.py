"""Unit under test: `accounts.mail.tasks.MailQueue` and `MailDelivery`, how a message gets from the request that
wants it
sent to the mailer, and what the mail log says about it.

Why: a sign-up request must answer in the same time whether or not the address has an account, and must not fail
because a
provider is down, so mail is sent by a Celery task, never in the request. The task can be delivered twice or
retried, so it
must send once, retry what is worth retrying and give up on what is not, and the log must say which, with a reason
that never
holds a code or a body (the log row is read by staff and kept for 30 days).

Use cases:
- queueing writes a log row (kind, address, subject, backend, queued) and hands the task the row and the message
  only after the
  transaction commits, so a rolled-back request sends nothing
- a delivery marks the row sent with the time and the provider's id, and counts the attempt
- the outbox backend keeps the body on the row; every other backend leaves it empty
- a transient failure keeps the row queued and asks for a retry; on the last attempt it marks the row failed
- a permanent refusal marks the row failed at once, with no retry
- an unexpected error marks the row failed with the error's class name only
- a row already sent is not sent again (a redelivered task), and a row that was purged is skipped
- the reason kept is cut to fit and the mailer's messages are what it holds, not the message body
- the Celery task `accounts.send_mail` runs a delivery
"""

from datetime import UTC, datetime

import pytest
from support.clock import FakeClock

from accounts.mail.mailer import Mailer, MailMessage, PermanentMailError, SendResult, TransientMailError
from accounts.mail.registry import MailBackends
from accounts.mail.tasks import MailDelivery, MailQueue, Outcome, send_mail
from accounts.models import OutboundMail

pytestmark = pytest.mark.django_db

MESSAGE = MailMessage(
    to="ada@example.com", kind="signup_code", subject="Your Socra code", text="Code 123456", html="<p>Code 123456</p>"
)


class Scripted(Mailer):
    key = "scripted"

    def __init__(self, *outcomes, keeps_body=False):
        self.outcomes, self.sent, self.keeps_body = list(outcomes), [], keeps_body

    def send(self, message):
        self.sent.append(message)
        outcome = self.outcomes.pop(0) if self.outcomes else SendResult("m-1")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @classmethod
    def from_settings(cls):
        return cls()


def delivery(mailer, clock=None):
    class Only(MailBackends):
        def current(self):
            return mailer

    return MailDelivery(backends=Only(), clock=clock or FakeClock(datetime(2026, 11, 12, 9, 0, tzinfo=UTC)))


def queued(**fields):
    fields.setdefault("backend", "scripted")
    return OutboundMail.objects.create(kind="signup_code", to_email="ada@example.com", **fields)


def test_queueing_logs_the_mail_and_dispatches_only_after_commit(settings, django_capture_on_commit_callbacks):
    settings.MAIL_BACKEND = "outbox"
    dispatched = []

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        row = MailQueue(dispatch=lambda row_id, payload: dispatched.append((row_id, payload))).send(MESSAGE)
        assert dispatched == []  # not before the transaction is over

    assert (row.kind, row.to_email, row.subject, row.backend, row.status) == (
        "signup_code",
        "ada@example.com",
        "Your Socra code",
        "outbox",
        "queued",
    )
    assert row.body_text == ""
    for callback in callbacks:
        callback()
    assert dispatched == [(row.pk, MESSAGE.as_payload())]
    assert MailMessage.from_payload(dispatched[0][1]) == MESSAGE


def test_a_delivery_marks_the_row_sent_with_the_time_and_the_provider_id():
    row, mailer = queued(), Scripted(SendResult("msg-42"))

    outcome = delivery(mailer).deliver(row.pk, MESSAGE.as_payload())

    row.refresh_from_db()
    assert outcome is Outcome.SENT and mailer.sent == [MESSAGE]
    assert (row.status, row.provider_message_id, row.attempts, row.error) == ("sent", "msg-42", 1, "")
    assert row.sent_at == datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    assert row.body_text == ""


def test_the_outbox_backend_keeps_the_body_and_no_other_does():
    kept, plain = queued(), queued()

    delivery(Scripted(keeps_body=True)).deliver(kept.pk, MESSAGE.as_payload())
    delivery(Scripted()).deliver(plain.pk, MESSAGE.as_payload())

    kept.refresh_from_db(), plain.refresh_from_db()
    assert kept.body_text == "Code 123456" and plain.body_text == ""


def test_a_transient_failure_asks_for_a_retry_and_the_last_attempt_gives_up():
    row = queued()
    mailer = Scripted(TransientMailError("provider busy"), TransientMailError("provider busy"))

    first = delivery(mailer).deliver(row.pk, MESSAGE.as_payload())
    row.refresh_from_db()
    assert first is Outcome.RETRY and (row.status, row.attempts, row.error) == ("queued", 1, "provider busy")

    OutboundMail.objects.filter(pk=row.pk).update(attempts=MailDelivery.MAX_ATTEMPTS - 1)
    last = delivery(mailer).deliver(row.pk, MESSAGE.as_payload())
    row.refresh_from_db()
    assert last is Outcome.FAILED and row.status == "failed" and row.attempts == MailDelivery.MAX_ATTEMPTS


def test_a_permanent_refusal_fails_at_once_with_no_retry():
    row = queued()

    outcome = delivery(Scripted(PermanentMailError("Brevo refused it: invalid_parameter"))).deliver(
        row.pk, MESSAGE.as_payload()
    )

    row.refresh_from_db()
    assert outcome is Outcome.FAILED and (row.status, row.attempts) == ("failed", 1)
    assert row.error == "Brevo refused it: invalid_parameter"


def test_an_unexpected_error_fails_the_row_with_only_the_class_name():
    row = queued()

    outcome = delivery(Scripted(RuntimeError("boom 123456 ada@example.com"))).deliver(row.pk, MESSAGE.as_payload())

    row.refresh_from_db()
    assert outcome is Outcome.FAILED and row.status == "failed"
    assert row.error == "RuntimeError" and "123456" not in row.error


def test_a_row_already_sent_is_not_sent_again_and_a_purged_row_is_skipped():
    row, mailer = queued(status="sent"), Scripted()

    assert delivery(mailer).deliver(row.pk, MESSAGE.as_payload()) is Outcome.SKIPPED
    assert delivery(mailer).deliver(row.pk + 1000, MESSAGE.as_payload()) is Outcome.SKIPPED
    assert mailer.sent == []


def test_the_reason_kept_is_cut_to_fit_the_column():
    row = queued()

    delivery(Scripted(PermanentMailError("x" * 1000))).deliver(row.pk, MESSAGE.as_payload())

    row.refresh_from_db()
    assert len(row.error) == 255


def test_the_celery_task_runs_a_delivery(settings):
    settings.DEBUG, settings.MAIL_ALLOW_OUTBOX, settings.MAIL_BACKEND = True, True, "outbox"
    row = queued(backend="outbox")

    result = send_mail.apply(args=[row.pk, MESSAGE.as_payload()])

    row.refresh_from_db()
    assert send_mail.name == "accounts.send_mail" and result.successful()
    assert row.status == "sent" and row.body_text == "Code 123456"

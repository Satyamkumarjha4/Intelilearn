"""Mail in tests: every message goes to a `Mailbox` instead of a provider, at once, and a test reads the code from it.

`RecordingMailer` is a backend registered under `recording` (the autouse fixture in `tests/conftest.py` selects it);
`InlineDispatch` replaces the Celery hand-off so a queued message is delivered when its transaction commits, with no
broker. `Mailbox` is what a test reads: the messages in the order they were sent."""

import re
from dataclasses import dataclass, field

from accounts.mail.mailer import Mailer, MailMessage, SendResult
from accounts.mail.registry import MailBackends
from accounts.mail.tasks import MailDelivery


@dataclass
class Mailbox:
    messages: list[MailMessage] = field(default_factory=list)

    def to(self, address: str, kind: str | None = None) -> list[MailMessage]:
        return [m for m in self.messages if m.to.lower() == address.lower() and (kind is None or m.kind == kind)]

    def code_for(self, address: str, kind: str = "signup_code") -> str:
        """The code in the latest message of `kind` to `address`."""
        found = self.to(address, kind)
        assert found, f"no {kind} was sent to {address}; sent: {[(m.kind, m.to) for m in self.messages]}"
        return re.search(r"\b(\d{6})\b", found[-1].text).group(1)


MAILBOX = Mailbox()


@MailBackends.register
class RecordingMailer(Mailer):
    key = "recording"
    keeps_body = True

    def send(self, message: MailMessage) -> SendResult:
        MAILBOX.messages.append(message)
        return SendResult(f"recorded-{len(MAILBOX.messages)}")

    @classmethod
    def from_settings(cls) -> "RecordingMailer":
        return cls()


class InlineDispatch:
    def __call__(self, row_id: int, payload: dict) -> object:
        return MailDelivery().deliver(row_id, payload)

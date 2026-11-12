"""The port every email backend implements, and the values that pass through it.

A backend is one subclass of `Mailer`, one line in the registry (`@MailBackends.register`) and its settings:
nothing that wants
a code sent knows which provider carries it. The errors say whether trying again can help.
"""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True)
class MailMessage:
    """One email. `kind` is what the mail log shows (`signup_code`, `reset_code`...); the text part is always there."""

    to: str
    kind: str
    subject: str
    text: str
    html: str = ""

    def as_payload(self) -> dict:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict) -> "MailMessage":
        return cls(**payload)


@dataclass(frozen=True)
class SendResult:
    message_id: str = ""


class MailError(Exception):
    """A message could not be sent. The text is a short reason that is safe to store: never a code, a body or a key."""


class TransientMailError(MailError):
    """Worth trying again later: the provider was busy or unreachable."""


class PermanentMailError(MailError):
    """Trying again cannot help: the provider refused it, or this backend is not allowed to run here."""


class Mailer(ABC):
    key: ClassVar[str]
    #: Whether the mail log keeps the text of what was sent. Only the throwaway-stack outbox does.
    keeps_body: ClassVar[bool] = False

    @abstractmethod
    def send(self, message: MailMessage) -> SendResult: ...

    @classmethod
    @abstractmethod
    def from_settings(cls) -> "Mailer": ...

    def missing_config(self) -> list[str]:
        """The names of the settings this backend needs and does not have (for the system check)."""
        return []

"""Which addresses may sign up (plan 6.3): a chain of rules, each one class.

A new rule is a new `EmailRule` added to the chain in `EmailPolicy`; the chain never grows an `if`. A refusal says what
to do, in the words a learner reads, and never names a list (we do not teach people which domains to avoid)."""

from abc import ABC, abstractmethod

from .canonical import EmailCanonicalizer, MalformedEmail
from .disposable import DisposableDomains


class EmailRefused(Exception):
    """The address cannot be used to sign up. `message` is what the person reads; `reason` is for the abuse board
    (`malformed` or `disposable`)."""

    def __init__(self, message: str, reason: str = ""):
        super().__init__(message)
        self.message, self.reason = message, reason


class EmailRule(ABC):
    @abstractmethod
    def check(self, email: str) -> None:
        """Raises `EmailRefused`, or returns."""


class WellFormed(EmailRule):
    MESSAGE = "That doesn't look like an email address."

    def check(self, email: str) -> None:
        try:
            EmailCanonicalizer.of(email)
        except MalformedEmail as error:
            raise EmailRefused(self.MESSAGE, "malformed") from error


class NotDisposable(EmailRule):
    MESSAGE = "Please use an email address you read regularly. Temporary email addresses can't be used."

    def __init__(self, domains: DisposableDomains | None = None):
        self._domains = domains

    @property
    def domains(self) -> DisposableDomains:
        return self._domains or DisposableDomains.default()

    def check(self, email: str) -> None:
        if self.domains.blocks(email.strip().rpartition("@")[2]):
            raise EmailRefused(self.MESSAGE, "disposable")


class EmailPolicy:
    def __init__(self, rules: tuple[EmailRule, ...] | None = None):
        self.rules = rules if rules is not None else (WellFormed(), NotDisposable())

    def check(self, email: str) -> str:
        """The canonical form of `email` if every rule accepts it; otherwise raises `EmailRefused`."""
        for rule in self.rules:
            rule.check(email)
        return EmailCanonicalizer.of(email)

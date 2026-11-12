"""The port every sign-in provider implements, and the values that pass through it (plan 6.1, T4).

A provider is one subclass of `IdentityProvider`, one line in the registry and its settings. What a provider decides is
whether the email it hands over is **verified**: that rule is its own (Google's `email_verified`; Microsoft's, when it
comes, is different), so the linking policy never has to know which provider spoke."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class VerifiedIdentity:
    """Who the provider says the person is. `subject` is the provider's stable id for them (never the email)."""

    provider: str
    subject: str
    email: str
    email_verified: bool
    name: str = ""
    hosted_domain: str = ""
    #: What an account's `email_verification_source` becomes when this identity proves its inbox (`google`, ...).
    #: The stand-in provider says `google`, so it is held to exactly the rules Google is. Blank: the provider's own key.
    verification_source: str = ""

    @property
    def source(self) -> str:
        return self.verification_source or self.provider


class ProviderError(Exception):
    """A sign-in that cannot go on. `code` is what the sign-in page is told (`?error=<code>`); `detail` is for the log
    only and never holds a token, a code or a secret."""

    CODES = ("email_not_verified", "provider_off", "state_mismatch", "sign_in_failed", "account_closed")

    def __init__(self, code: str, detail: str = ""):
        assert code in self.CODES, code
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


class IdentityProvider(ABC):
    key: ClassVar[str]
    display_name: ClassVar[str]

    @abstractmethod
    def start(self, ticket, redirect_uri: str, options: Mapping[str, str]) -> str:
        """The address to send the person to, so they sign in with the provider. `ticket` is the `OAuthTicket` (state,
        nonce, PKCE challenge); `options` are the query parameters of our own start request (only the fake provider
        reads them)."""

    @abstractmethod
    def complete(self, params: Mapping[str, str], ticket, redirect_uri: str) -> VerifiedIdentity:
        """What came back on the callback, turned into a verified identity. Raises `ProviderError`."""

    @classmethod
    @abstractmethod
    def from_settings(cls) -> "IdentityProvider": ...

    def missing_config(self) -> list[str]:
        """The names of the settings this provider needs and does not have (for the system check)."""
        return []

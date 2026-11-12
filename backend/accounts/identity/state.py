"""The two short-lived signed cookies of the sign-in dance (plan T12), and the PKCE pair.

`lc_oauth` holds what the callback must find again: the `state` we sent, the `nonce` the ID token must carry, the PKCE
verifier and where to go afterwards. It is signed (a person cannot change what is in it) and httpOnly, so it carries no
authority: it only proves that this browser started this sign-in a few minutes ago. `lc_finish` holds a verified
identity
waiting for the "one last step" screen; it too only says "this browser just came back from the provider"."""

import base64
import hashlib
import secrets
from dataclasses import asdict, dataclass

from django.conf import settings
from django.core import signing

from ..redirect import RedirectPolicy
from .provider import ProviderError, VerifiedIdentity


@dataclass(frozen=True)
class OAuthTicket:
    provider: str
    state: str
    nonce: str
    verifier: str
    next: str

    @property
    def challenge(self) -> str:
        """The PKCE `S256` challenge of the verifier (RFC 7636): base64url of its SHA-256, no padding."""
        digest = hashlib.sha256(self.verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OAuthState:
    COOKIE = "lc_oauth"
    SALT = "accounts.oauth-state"

    def issue(self, provider: str, next_value: object) -> OAuthTicket:
        return OAuthTicket(
            provider=provider,
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            verifier=secrets.token_urlsafe(48),  # 64 characters: inside RFC 7636's 43 to 128
            next=RedirectPolicy.safe_next(next_value),
        )

    def seal(self, ticket: OAuthTicket) -> str:
        return signing.dumps(asdict(ticket), salt=self.SALT, compress=False)

    @property
    def max_age(self) -> int:
        return settings.OAUTH_STATE_MINUTES * 60

    def read(self, cookie: str | None) -> OAuthTicket | None:
        """The ticket in a cookie, or None for a missing, forged, tampered or expired one."""
        if not cookie:
            return None
        try:
            return OAuthTicket(**signing.loads(cookie, salt=self.SALT, max_age=self.max_age))
        except (signing.BadSignature, TypeError, ValueError):
            return None

    def check(self, cookie: str | None, returned_state: str | None, provider: str) -> OAuthTicket:
        """The ticket, once the `state` that came back is the one we sent from this browser (and for this provider)."""
        ticket = self.read(cookie)
        if ticket is None or ticket.provider != provider or not returned_state:
            raise ProviderError("state_mismatch", "no ticket, another provider, or no state")
        if not secrets.compare_digest(ticket.state.encode(), returned_state.encode()):
            raise ProviderError("state_mismatch", "state differs")
        return ticket


@dataclass(frozen=True)
class FinishTicket:
    """A verified identity waiting for the person to give their name and agree to the terms."""

    identity: VerifiedIdentity
    next: str


class FinishState:
    COOKIE = "lc_finish"
    SALT = "accounts.oauth-finish"

    def seal(self, ticket: FinishTicket) -> str:
        return signing.dumps({"identity": asdict(ticket.identity), "next": ticket.next}, salt=self.SALT, compress=False)

    @property
    def max_age(self) -> int:
        return settings.OAUTH_FINISH_MINUTES * 60

    def read(self, cookie: str | None) -> FinishTicket | None:
        if not cookie:
            return None
        try:
            data = signing.loads(cookie, salt=self.SALT, max_age=self.max_age)
            return FinishTicket(
                identity=VerifiedIdentity(**data["identity"]), next=RedirectPolicy.safe_next(data["next"])
            )
        except (signing.BadSignature, TypeError, ValueError, KeyError):
            return None

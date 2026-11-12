"""A stand-in provider for browser tests (plan T4, T17): it answers the redirect itself, with an identity the caller
names.

It is **never** on in production: it needs `AUTH_ALLOW_FAKE_PROVIDER`, which `accounts.E006` refuses unless
`DJANGO_DEBUG` is on, and it must be named in `AUTH_PROVIDERS_ENABLED` (`accounts.E005`). Nothing here is a shortcut
round the callback: the fake's redirect goes to the real callback with the real `state`, so the state check, the linking
policy and the cookies all run.

The test names who is signing in with `?fake=<json>` on the start address: `{"subject", "email", "email_verified",
"name"}`. With nothing named, each start is a new person.
"""

import base64
import json
import secrets
from collections.abc import Mapping
from urllib.parse import urlencode

from .provider import IdentityProvider, ProviderError, VerifiedIdentity
from .registry import IdentityProviders
from .state import OAuthTicket


@IdentityProviders.register
class FakeProvider(IdentityProvider):
    key = "fake"
    display_name = "Google (test)"

    def start(self, ticket: OAuthTicket, redirect_uri: str, options: Mapping[str, str]) -> str:
        named = self._named(options.get("fake", ""))
        who = secrets.token_hex(6)
        identity = {
            "subject": f"fake-{who}",
            "email": f"fake-{who}@example.com",
            "email_verified": True,
            "name": "Fake Person",
            **named,
        }
        code = base64.urlsafe_b64encode(json.dumps(identity).encode()).decode().rstrip("=")
        return f"{redirect_uri}?{urlencode({'code': code, 'state': ticket.state})}"

    def complete(self, params: Mapping[str, str], ticket: OAuthTicket, redirect_uri: str) -> VerifiedIdentity:
        if params.get("error"):
            raise ProviderError("sign_in_failed", "the fake provider was told to fail")
        try:
            raw = params["code"]
            data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            verified = data.get("email_verified") is True
            return VerifiedIdentity(
                provider=self.key,
                subject=str(data["subject"]),
                email=str(data["email"]),
                email_verified=verified,
                name=str(data.get("name", "")),
                hosted_domain=str(data.get("hosted_domain", "")),
                verification_source="google",  # it stands in for Google, so it is held to Google's rules
            )
        except (KeyError, ValueError, TypeError) as error:
            raise ProviderError("sign_in_failed", "the fake code could not be read") from error

    @classmethod
    def from_settings(cls) -> "FakeProvider":
        return cls()

    @staticmethod
    def _named(text: str) -> dict:
        try:
            value = json.loads(text) if text else {}
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

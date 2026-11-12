"""Sign in with Google: the server-side authorization-code flow (plan T5, T6).

The person is sent to Google with `state`, `nonce` and a PKCE challenge; Google redirects back to our own callback with
a `code`; **we** exchange it (with the client secret and the PKCE verifier) for an ID token, so no token ever reaches
the browser's JavaScript, and check the token (`IdTokenValidator`). The person is keyed by Google's `sub`, never by
email.

What the documentation does and does not say is in plan U4. Notably: `nonce` is worded both as required and as
optional, so it is always sent and always checked; PKCE is listed in Google's discovery document
(`code_challenge_methods_supported`) but the web-server page never shows its parameters, so it is sent as RFC 7636 says
and confirmed against a real client before launch (unverified); and `email_verified` is not described as a boolean (its
example shows the string "true"), so this class accepts only the boolean `true` and a real token must be checked once
(unverified).
"""

import logging
from collections.abc import Mapping
from typing import ClassVar
from urllib.parse import urlencode

import httpx
from django.conf import settings

from .provider import IdentityProvider, ProviderError, VerifiedIdentity
from .registry import IdentityProviders
from .state import OAuthTicket
from .tokens import HttpJwks, IdTokenValidator, InvalidIdToken, JwksSource

logger = logging.getLogger(__name__)


@IdentityProviders.register
class GoogleProvider(IdentityProvider):
    key = "google"
    display_name = "Google"

    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
    ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})  # the two the documentation lists
    SCOPE = "openid email profile"
    TIMEOUT_S = 10

    _shared_jwks: ClassVar[JwksSource | None] = None

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        http: httpx.Client | None = None,
        jwks: JwksSource | None = None,
        validator: IdTokenValidator | None = None,
    ):
        self.client_id, self.client_secret = client_id, client_secret
        self._http, self._jwks = http, jwks
        self.validator = validator or IdTokenValidator(self.ISSUERS, client_id)

    @classmethod
    def from_settings(cls) -> "GoogleProvider":
        return cls(settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET)

    def missing_config(self) -> list[str]:
        return [
            name
            for name, value in (
                ("GOOGLE_OAUTH_CLIENT_ID", self.client_id),
                ("GOOGLE_OAUTH_CLIENT_SECRET", self.client_secret),
            )
            if not value
        ]

    def start(self, ticket: OAuthTicket, redirect_uri: str, options: Mapping[str, str]) -> str:
        query = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.SCOPE,
            "state": ticket.state,
            "nonce": ticket.nonce,
            "code_challenge": ticket.challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",  # a shared computer must not sign in as whoever Google last remembered
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(query)}"

    def complete(self, params: Mapping[str, str], ticket: OAuthTicket, redirect_uri: str) -> VerifiedIdentity:
        if params.get("error"):
            raise ProviderError("sign_in_failed", f"google answered error={params['error'][:40]}")  # e.g. access_denied
        code = params.get("code")
        if not code:
            raise ProviderError("sign_in_failed", "no code on the callback")
        with self._client() as http:
            raw = self._exchange(http, code, ticket, redirect_uri)
            try:
                claims = self.validator.validate(raw, self._jwks or self._shared(http), ticket.nonce)
            except InvalidIdToken as error:
                raise ProviderError("sign_in_failed", f"id token refused: {error.reason}") from error
        # Only the boolean `true` is Google calling the address verified (not the string "true", nothing, or false).
        email = claims.get("email")
        if claims.get("email_verified") is not True or not isinstance(email, str) or not email:
            raise ProviderError("email_not_verified", "google did not call the email verified")
        return VerifiedIdentity(
            provider=self.key,
            subject=claims["sub"],
            email=email,
            email_verified=True,
            name=str(claims.get("name") or "")[:150],
            hosted_domain=str(claims.get("hd") or "")[:255],
            verification_source="google",
        )

    def _exchange(self, http: httpx.Client, code: str, ticket: OAuthTicket, redirect_uri: str) -> str:
        try:
            response = http.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": ticket.verifier,
                },
            )
        except httpx.HTTPError as error:
            raise ProviderError("sign_in_failed", f"token request failed: {type(error).__name__}") from error
        if response.status_code != 200:
            raise ProviderError("sign_in_failed", f"token endpoint answered {response.status_code}")  # never its body
        try:
            raw = response.json()["id_token"]
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderError("sign_in_failed", "no id_token in the answer") from error
        return str(raw)

    def _client(self):
        """The injected client (not closed here), or a fresh one for this call."""
        if self._http is not None:
            return _Borrowed(self._http)
        return httpx.Client(timeout=self.TIMEOUT_S)

    def _shared(self, http: httpx.Client) -> JwksSource:
        """Google's keys, fetched once per process and kept as long as Google's cache headers say."""
        if GoogleProvider._shared_jwks is None:
            GoogleProvider._shared_jwks = HttpJwks(httpx.Client(timeout=self.TIMEOUT_S), self.JWKS_URL)
        return GoogleProvider._shared_jwks


class _Borrowed:
    """Lets `with` use an injected client without closing it."""

    def __init__(self, client: httpx.Client):
        self.client = client

    def __enter__(self) -> httpx.Client:
        return self.client

    def __exit__(self, *exc) -> None:
        return None

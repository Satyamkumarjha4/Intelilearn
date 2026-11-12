"""Checking an OpenID Connect ID token (plan T11): signature, issuer, audience, expiry and nonce; nothing else trusted.

PyJWT does the cryptography; this class decides what to ask of it. The algorithm is read from the token's header
**before** anything is verified and refused unless it is on our short list (so `alg: none` and an HMAC signed with a
public key never get as far as a key). Every check that Google's documentation lists is made, and `nonce` is
**always** checked, though the page words it as optional in one place and required in another (plan U4).
"""

import hmac
import time
from collections.abc import Mapping
from typing import Any, Protocol

import httpx
import jwt


class InvalidIdToken(Exception):
    """The token cannot be trusted. `reason` is for the log and never holds the token."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class JwksSource(Protocol):
    def key_for(self, kid: str | None) -> Any:
        """The public key that signed a token with this `kid`. Raises `KeyError` when there is none."""


class StaticJwks:
    """A fixed set of keys: a test's own, or a provider whose keys are pinned."""

    def __init__(self, keys: Mapping[str, Any]):
        self.keys = dict(keys)

    def key_for(self, kid: str | None) -> Any:
        if kid is None or kid not in self.keys:
            raise KeyError(kid)
        return self.keys[kid]


class HttpJwks:
    """The provider's published keys, fetched over HTTPS and kept as long as its `Cache-Control: max-age` says (an hour
    when it says nothing). A `kid` we have not seen refetches, at most once a minute, so a key rotation is picked up
    and an attacker's made-up `kid` cannot make us fetch in a loop."""

    DEFAULT_MAX_AGE = 3600
    REFETCH_FLOOR = 60

    def __init__(self, client: httpx.Client, url: str, clock=time.monotonic):
        self.client, self.url, self.clock = client, url, clock
        self._keys: dict[str, Any] = {}
        self._fetched_at: float | None = None
        self._max_age = self.DEFAULT_MAX_AGE

    def key_for(self, kid: str | None) -> Any:
        now = self.clock()
        stale = self._fetched_at is None or now - self._fetched_at > self._max_age
        unknown = kid not in self._keys and (self._fetched_at is None or now - self._fetched_at >= self.REFETCH_FLOOR)
        if stale or unknown:
            self._fetch(now)
        if kid is None or kid not in self._keys:
            raise KeyError(kid)
        return self._keys[kid]

    def _fetch(self, now: float) -> None:
        try:
            response = self.client.get(self.url)
            response.raise_for_status()
            document = response.json()
            keys = {
                item["kid"]: jwt.PyJWK(item).key
                for item in document["keys"]
                if item.get("kty") == "RSA" and "kid" in item
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError) as error:
            raise InvalidIdToken(f"keys could not be fetched: {type(error).__name__}") from error
        self._keys, self._fetched_at = keys, now
        self._max_age = self._max_age_of(response.headers.get("cache-control", ""))

    @classmethod
    def _max_age_of(cls, header: str) -> int:
        for part in header.split(","):
            name, _, value = part.strip().partition("=")
            if name.lower() == "max-age" and value.strip().isdigit():
                return int(value)
        return cls.DEFAULT_MAX_AGE


class IdTokenValidator:
    REQUIRED = ["exp", "iss", "aud", "sub", "iat"]

    def __init__(
        self, issuers: frozenset[str], audience: str, algorithms: tuple[str, ...] = ("RS256",), leeway: int = 60
    ):
        self.issuers, self.audience, self.algorithms, self.leeway = issuers, audience, algorithms, leeway

    def validate(self, raw: str, jwks: JwksSource, nonce: str) -> dict:
        """The claims of a token that passes every check, or `InvalidIdToken`."""
        if not nonce:
            raise InvalidIdToken("no nonce to check against")  # a token is never accepted without one to compare
        try:
            header = jwt.get_unverified_header(raw)
        except jwt.PyJWTError as error:
            raise InvalidIdToken("not a token") from error
        if header.get("alg") not in self.algorithms:
            raise InvalidIdToken(f"algorithm {header.get('alg')!r} is not accepted")
        try:
            key = jwks.key_for(header.get("kid"))
        except KeyError as error:
            raise InvalidIdToken("no key for this token") from error
        try:
            claims = jwt.decode(
                raw,
                key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                leeway=self.leeway,
                options={"require": self.REQUIRED},
            )
        except jwt.PyJWTError as error:
            raise InvalidIdToken(type(error).__name__) from error
        if claims["iss"] not in self.issuers:
            raise InvalidIdToken("wrong issuer")
        if not hmac.compare_digest(str(claims.get("nonce", "")).encode(), nonce.encode()):
            raise InvalidIdToken("wrong nonce")
        subject = claims["sub"]
        if not isinstance(subject, str) or not 0 < len(subject) <= 255:
            raise InvalidIdToken("bad subject")
        return claims

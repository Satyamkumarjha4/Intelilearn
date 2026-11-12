"""A stand-in for Google's OpenID Connect endpoints that signs REAL ID tokens, so the validator is proved against
genuine signatures, not stubs (plan 13.6).

`FakeGoogle` owns an RSA key pair, publishes the public half as a JWKS, signs tokens with the private half (PyJWT) and
answers the token endpoint through an `httpx.MockTransport`. A test changes one thing about a token (the audience, the
nonce, the algorithm, the key) and checks that it is refused. Nothing here touches the network."""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

CLIENT_ID = "test-client-id.apps.example"
KID = "test-key-1"


def _int_b64(number: int) -> str:
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@dataclass
class FakeGoogle:
    audience: str = CLIENT_ID
    key: rsa.RSAPrivateKey = field(
        default_factory=lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    token_status: int = 200
    id_token: str | None = None  # what the token endpoint hands back; None means "make a good one for the last request"
    requests: list = field(default_factory=list)
    jwks_fetches: int = 0
    cache_control: str | None = None

    @property
    def public_numbers(self):
        return self.key.public_key().public_numbers()

    def jwks(self) -> dict:
        numbers = self.public_numbers
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": KID,
                    "use": "sig",
                    "alg": "RS256",
                    "n": _int_b64(numbers.n),
                    "e": _int_b64(numbers.e),
                }
            ]
        }

    def claims(self, nonce: str, **overrides) -> dict:
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com",
            "aud": self.audience,
            "sub": "10769150350006150715113082367",
            "email": "ada@example.com",
            "email_verified": True,
            "name": "Ada Lovelace",
            "nonce": nonce,
            "iat": now,
            "exp": now + 3600,
        }
        claims.update(overrides)
        return {key: value for key, value in claims.items() if value is not _MISSING}

    def sign(self, claims: dict, *, key=None, algorithm: str = "RS256", kid: str | None = KID) -> str:
        headers = {"kid": kid} if kid else {}
        return jwt.encode(claims, key if key is not None else self.key, algorithm=algorithm, headers=headers)

    def unsigned(self, claims: dict) -> str:
        """A token with `alg: none` and no signature."""
        return jwt.encode(claims, None, algorithm="none", headers={"kid": KID})

    def hmac_token(self, claims: dict, secret: bytes) -> str:
        """An HS256 token made by hand (PyJWT refuses to sign HMAC with an RSA key, as an attacker would)."""

        def part(value: dict) -> str:
            return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

        signing_input = f"{part({'alg': 'HS256', 'typ': 'JWT', 'kid': KID})}.{part(claims)}"
        signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
        return f"{signing_input}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"

    def stripped(self, claims: dict) -> str:
        """A well-formed RS256 token with its signature cut off."""
        return self.sign(claims).rsplit(".", 1)[0] + "."

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/certs"):
            self.jwks_fetches += 1
            headers = {"Cache-Control": self.cache_control} if self.cache_control else {}
            return httpx.Response(200, json=self.jwks(), headers=headers)
        form = dict(item.split("=", 1) for item in request.content.decode().split("&"))
        self.requests.append(form)
        if self.token_status != 200:
            return httpx.Response(
                self.token_status, json={"error": "invalid_grant", "error_description": "secret-detail"}
            )
        return httpx.Response(
            200, json={"access_token": "ya29.not-used", "token_type": "Bearer", "id_token": self.id_token}
        )

    def json_body(self) -> str:
        return json.dumps(self.jwks())


class _Missing:
    def __repr__(self):
        return "MISSING"


_MISSING = _Missing()
MISSING = _MISSING  # pass as a claim's value to leave the claim out

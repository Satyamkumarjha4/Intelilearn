"""A stand-in for Stripe's side of the wire, for the payment tests (credits plan §13.3, phase 10.7).

`Wire` is the handler of an `httpx.MockTransport`: it answers from a list a test gives it and records every request,
so a test can read exactly what the adapter sent. `signature` signs a webhook body the way Stripe does.
"""

import hashlib
import hmac
from datetime import datetime

import httpx


class Wire:
    """A Stripe that answers from a list (the last answer repeats) and records what it was sent. An answer is
    `(status, body)` with a dict or a string body, or an exception to raise, as a dead connection does."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx.Response(status, text=body) if isinstance(body, str) else httpx.Response(status, json=body)

    @property
    def sent(self) -> httpx.Request:
        return self.requests[-1]

    def form(self, request: httpx.Request | None = None) -> dict[str, str]:
        from urllib.parse import parse_qs

        content = (request or self.sent).content.decode()
        return {k: v[0] for k, v in parse_qs(content, keep_blank_values=True).items()}

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def signature(body: bytes, secret: str, at: datetime, extra: str = "") -> str:
    """`Stripe-Signature` for `body`: `t=<seconds>,v1=<HMAC-SHA256 of "t.body">`."""
    stamp = int(at.timestamp())
    digest = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={stamp},v1={digest}{extra}"

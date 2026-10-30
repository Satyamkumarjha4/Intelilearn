"""The optional `Idempotency-Key` header on the creation endpoints (`POST /lessons`, `POST /lessons/{id}/materials`).

A client that repeats a request with the same key gets the first answer back and nothing else happens: no second
lesson, no second authorization. The key is scoped to the learner, the endpoint and the request body, so it can neither
leak between learners nor answer a different request. Answers are kept for `IDEMPOTENCY_TTL_S` in the cache (Redis).
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response

from .errors import LessonError


class InvalidIdempotencyKey(LessonError):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_idempotency_key"
    default_detail = "The Idempotency-Key header must be 1 to 128 printable characters without spaces."


class RequestInProgress(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "request_in_progress"
    default_detail = "The same request is still being handled. Try again in a moment."


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: Any


@dataclass(frozen=True)
class IdempotencyKey:
    header: str  # what the client sent
    cache_key: str  # the header made specific to the learner, endpoint and body

    HEADER = "Idempotency-Key"
    PATTERN = re.compile(r"[\x21-\x7e]{1,128}")

    @classmethod
    def of(cls, request, scope: str, body: Any) -> "IdempotencyKey | None":
        header = request.headers.get(cls.HEADER)
        if header is None:
            return None
        if not cls.PATTERN.fullmatch(header):
            raise InvalidIdempotencyKey()
        canonical = json.dumps(body, sort_keys=True, default=str)
        digest = hashlib.sha256(f"{request.user.pk}|{scope}|{header}|{canonical}".encode()).hexdigest()
        return cls(header, f"idempotency:{digest}")


class IdempotencyStore(Protocol):
    def replay(self, cache_key: str) -> StoredResponse | None: ...

    def claim(self, cache_key: str) -> bool: ...

    def remember(self, cache_key: str, response: StoredResponse) -> None: ...

    def release(self, cache_key: str) -> None: ...


class CacheIdempotencyStore:
    """On the Django cache, which is Redis outside the tests."""

    CLAIM_TTL_S = 60  # longer than a creation request takes; a crashed one frees the key itself

    def replay(self, cache_key: str) -> StoredResponse | None:
        stored = cache.get(cache_key)
        return StoredResponse(**stored) if stored else None

    def claim(self, cache_key: str) -> bool:
        return cache.add(f"{cache_key}:claim", "1", self.CLAIM_TTL_S)

    def remember(self, cache_key: str, response: StoredResponse) -> None:
        cache.set(cache_key, {"status": response.status, "body": response.body}, settings.IDEMPOTENCY_TTL_S)

    def release(self, cache_key: str) -> None:
        cache.delete(f"{cache_key}:claim")


class IdempotentRequest:
    def __init__(self, store: IdempotencyStore | None = None):
        self.store = store or CacheIdempotencyStore()

    def run(self, request, scope: str, body: Any, perform: Callable[[str], Response]) -> Response:
        """Perform the request once per key. `perform` gets the client's key (or "") to pass on to the gate."""
        key = IdempotencyKey.of(request, scope, body)
        if key is None:
            return perform("")
        if stored := self.store.replay(key.cache_key):
            replayed = Response(stored.body, status=stored.status)
            replayed["Idempotent-Replayed"] = "true"
            return replayed
        if not self.store.claim(key.cache_key):
            raise RequestInProgress()
        try:
            response = perform(key.header)
            if 200 <= response.status_code < 300:
                self.store.remember(key.cache_key, StoredResponse(response.status_code, response.data))
            return response
        finally:
            self.store.release(key.cache_key)

"""Which model errors are worth retrying on the same model, and how long to wait first (Strategy)."""

import random
from collections.abc import Callable
from typing import Protocol

from .providers import MissingAPIKey
from .ratelimit import RateLimitWaitExceeded


class RetryPolicy(Protocol):
    def is_retryable(self, exc: Exception) -> bool: ...

    def delay(self, attempt: int, exc: Exception) -> float: ...


class ExponentialBackoffPolicy:
    """Retry timeouts, 429, 5xx and connection errors with jittered exponential backoff, honouring Retry-After."""

    RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
    # SDK exception class names that mean "transient" when no status code is attached.
    RETRYABLE_NAMES = ("Timeout", "RateLimit", "Connection", "InternalServer", "ServiceUnavailable", "Overloaded")
    # Errors that will fail the same way on every retry.
    NEVER_RETRY = (MissingAPIKey, RateLimitWaitExceeded)

    def __init__(self, base_s: float = 1.0, max_s: float = 30.0, jitter: Callable[[], float] = random.random):
        self.base_s, self.max_s, self._jitter = base_s, max_s, jitter

    def is_retryable(self, exc: Exception) -> bool:
        if isinstance(exc, self.NEVER_RETRY):
            return False
        if isinstance(exc, TimeoutError | ConnectionError):
            return True
        status = self._status_code(exc)
        if status is not None:
            return status in self.RETRYABLE_STATUS
        names = [cls.__name__ for cls in type(exc).__mro__]
        return any(marker in name for name in names for marker in self.RETRYABLE_NAMES)

    def delay(self, attempt: int, exc: Exception) -> float:
        if (hinted := self._retry_after(exc)) is not None:
            return min(hinted, self.max_s)
        return min(self.base_s * 2 ** (attempt - 1), self.max_s) * (0.5 + self._jitter() / 2)

    @staticmethod
    def _status_code(exc: Exception) -> int | None:
        for candidate in (exc, getattr(exc, "response", None)):
            for attr in ("status_code", "status", "code"):
                value = getattr(candidate, attr, None)
                if isinstance(value, int) and 100 <= value < 600:
                    return value
        return None

    @staticmethod
    def _retry_after(exc: Exception) -> float | None:
        headers = getattr(getattr(exc, "response", None), "headers", None) or {}
        try:
            value = headers.get("retry-after")
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

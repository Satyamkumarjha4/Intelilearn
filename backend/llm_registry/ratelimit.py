"""Requests-per-minute limits per provider and per model, shared by all workers through the cache (Redis).

Fixed one-minute windows: a call that would exceed a limit waits for the next window instead of failing,
which replaces the original project's `sleep(4000)` between agents.
"""

import time
from collections.abc import Callable, Mapping
from typing import Protocol

from django.core.cache import cache as default_cache


class RateLimitWaitExceeded(RuntimeError):
    pass


class RateLimiter(Protocol):
    def acquire(self, limits: Mapping[str, int | None]) -> float:
        """Block until every scope in `limits` has room; return the seconds waited."""


class CacheWindowRateLimiter:
    WINDOW_S = 60
    MAX_WAIT_S = 120

    def __init__(
        self,
        *,
        cache=None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        max_wait_s: float | None = None,
    ):
        self._cache = cache if cache is not None else default_cache
        self._sleep, self._clock = sleep, clock
        self.max_wait_s = max_wait_s if max_wait_s is not None else self.MAX_WAIT_S

    def acquire(self, limits: Mapping[str, int | None]) -> float:
        waited = 0.0
        for scope, limit in limits.items():
            if not limit:
                continue
            while (delay := self._try_take(scope, limit, self._clock())) > 0:
                if waited + delay > self.max_wait_s:
                    raise RateLimitWaitExceeded(
                        f"Rate limit for {scope} would need more than {self.max_wait_s}s of waiting."
                    )
                self._sleep(delay)
                waited += delay
        return waited

    def _try_take(self, scope: str, limit: int, now: float) -> float:
        """Take one request from the current window; return 0 on success, else seconds until the next window."""
        window = int(now // self.WINDOW_S)
        key = f"llm_rpm:{scope}:{window}"
        self._cache.add(key, 0, timeout=2 * self.WINDOW_S)
        try:
            count = self._cache.incr(key)
        except ValueError:  # key evicted between add and incr
            self._cache.set(key, 1, timeout=2 * self.WINDOW_S)
            count = 1
        if count <= limit:
            return 0.0
        return (window + 1) * self.WINDOW_S - now + 0.05

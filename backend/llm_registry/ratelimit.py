"""Requests-per-minute limits per provider and per model, shared by all workers through the cache (Redis).

Fixed one-minute windows: a call that would exceed a limit waits for the next window instead of failing,
which replaces the original project's `sleep(4000)` between agents.
"""

import time
from collections.abc import Callable

from django.core.cache import cache

MAX_WAIT_S = 120


class RateLimitWaitExceeded(RuntimeError):
    pass


def _window_key(scope: str, window: int) -> str:
    return f"llm_rpm:{scope}:{window}"


def _try_take(scope: str, limit: int, now: float) -> float:
    """Take one request from the current window; return 0 on success, else seconds until the next window."""
    window = int(now // 60)
    key = _window_key(scope, window)
    cache.add(key, 0, timeout=120)
    try:
        count = cache.incr(key)
    except ValueError:  # key evicted between add and incr
        cache.set(key, 1, timeout=120)
        count = 1
    if count <= limit:
        return 0.0
    return (window + 1) * 60 - now + 0.05


def acquire(
    limits: dict[str, int | None],
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> float:
    """Block until every scope in `limits` has room. Returns the seconds waited."""
    waited = 0.0
    for scope, limit in limits.items():
        if not limit:
            continue
        while (delay := _try_take(scope, limit, clock())) > 0:
            if waited + delay > MAX_WAIT_S:
                raise RateLimitWaitExceeded(f"Rate limit for {scope} would need more than {MAX_WAIT_S}s of waiting.")
            sleep(delay)
            waited += delay
    return waited

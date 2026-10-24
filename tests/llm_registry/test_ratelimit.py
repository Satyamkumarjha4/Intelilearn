"""Unit under test: `llm_registry.ratelimit.CacheWindowRateLimiter`, per-minute request limits per provider and
model, shared by every worker through the cache.

Why: parallel graph branches call the same provider at once. Without a shared limit they exceed the plan's quota
and burn retries on 429s; waiting for the next window keeps a lesson running instead of failing it.

Use cases:
- calls within the limit don't wait
- a call over the limit waits until the next one-minute window
- every scope (provider and model) is checked
- scopes without a limit are ignored
- refuses to wait longer than max_wait_s
"""

import pytest

from llm_registry.ratelimit import CacheWindowRateLimiter, RateLimitWaitExceeded


class Clock:
    def __init__(self, now=16_667 * 60 + 20.0):  # 20s into a minute window
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept = getattr(self, "slept", []) + [seconds]
        self.now += seconds


def limiter(clock, **kwargs):
    return CacheWindowRateLimiter(sleep=clock.sleep, clock=clock, **kwargs)


def test_calls_within_the_limit_do_not_wait():
    clock = Clock()
    for _ in range(3):
        assert limiter(clock).acquire({"provider:x": 3}) == 0


def test_call_over_the_limit_waits_for_the_next_window():
    clock = Clock()
    for _ in range(2):
        limiter(clock).acquire({"provider:x": 2})

    waited = limiter(clock).acquire({"provider:x": 2})

    assert 39 < waited < 41  # 20s into the window → ~40s until the next one


def test_every_scope_is_checked():
    clock = Clock()
    limiter(clock).acquire({"provider:x": 10, "model:x/m": 1})

    assert limiter(clock).acquire({"provider:x": 10, "model:x/m": 1}) > 0


def test_unlimited_scopes_are_ignored():
    clock = Clock()
    for _ in range(50):
        assert limiter(clock).acquire({"provider:x": None}) == 0


def test_refuses_to_wait_forever():
    clock = Clock()
    short = limiter(clock, max_wait_s=10)
    short.acquire({"provider:x": 1})
    with pytest.raises(RateLimitWaitExceeded):
        short.acquire({"provider:x": 1})

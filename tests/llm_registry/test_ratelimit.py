import pytest

from llm_registry.ratelimit import RateLimitWaitExceeded, acquire


class Clock:
    def __init__(self, now=16_667 * 60 + 20.0):  # 20s into a minute window
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept = getattr(self, "slept", []) + [seconds]
        self.now += seconds


def test_calls_within_the_limit_do_not_wait():
    clock = Clock()
    for _ in range(3):
        assert acquire({"provider:x": 3}, sleep=clock.sleep, clock=clock) == 0


def test_call_over_the_limit_waits_for_the_next_window():
    clock = Clock()
    for _ in range(2):
        acquire({"provider:x": 2}, sleep=clock.sleep, clock=clock)

    waited = acquire({"provider:x": 2}, sleep=clock.sleep, clock=clock)

    assert 39 < waited < 41  # 20s into the window → ~40s until the next one


def test_every_scope_is_checked():
    clock = Clock()
    acquire({"provider:x": 10, "model:x/m": 1}, sleep=clock.sleep, clock=clock)

    assert acquire({"provider:x": 10, "model:x/m": 1}, sleep=clock.sleep, clock=clock) > 0


def test_unlimited_scopes_are_ignored():
    clock = Clock()
    for _ in range(50):
        assert acquire({"provider:x": None}, sleep=clock.sleep, clock=clock) == 0


def test_refuses_to_wait_forever(monkeypatch):
    monkeypatch.setattr("llm_registry.ratelimit.MAX_WAIT_S", 10)
    clock = Clock()
    acquire({"provider:x": 1}, sleep=clock.sleep, clock=clock)
    with pytest.raises(RateLimitWaitExceeded):
        acquire({"provider:x": 1}, sleep=clock.sleep, clock=clock)

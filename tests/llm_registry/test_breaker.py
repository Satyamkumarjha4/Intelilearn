"""Unit under test: `llm_registry.breaker.ProviderBreaker`, the circuit breaker that stops a chain from trying a
provider that has just refused its key or its billing.

Why: a 401 (bad or revoked key) or 402 (no credit) does not get better by trying again, but every call of every lesson
would still try that layer first and fail, adding a log row and a round trip each time. After three in a row the
provider is skipped for five minutes, then tried again, so a fixed key or a topped-up balance is picked up.

Use cases:
- three refusals (401 or 402) in a row open the breaker for the cool-down, then it closes by itself
- fewer than three do not open it
- a rate limit, a server error or a timeout is not a refusal and never counts
- one success resets the count
- refusals spread over more than the cool-down do not add up
- each provider has its own breaker
"""

import pytest

from llm_registry.breaker import ProviderBreaker


class FakeTtlCache:
    """The small part of Django's cache API the breaker uses, with a clock the test moves."""

    def __init__(self):
        self.now, self.items = 0.0, {}

    def get(self, key, default=None):
        value, expires = self.items.get(key, (default, None))
        return default if expires is not None and expires <= self.now else value

    def set(self, key, value, timeout=None):
        self.items[key] = (value, None if timeout is None else self.now + timeout)

    def delete(self, key):
        self.items.pop(key, None)


class Refused(Exception):
    def __init__(self, status):
        self.status_code = status


@pytest.fixture
def cache():
    return FakeTtlCache()


@pytest.fixture
def breaker(cache):
    return ProviderBreaker(cache=cache, failures=3, cooldown_s=300)


def refuse(breaker, provider="openai", status=401, times=1):
    for _ in range(times):
        breaker.record_failure(provider, Refused(status))


@pytest.mark.parametrize("status", [401, 402])
def test_three_refusals_in_a_row_open_it_for_the_cooldown_and_it_then_closes(breaker, cache, status):
    refuse(breaker, status=status, times=3)

    assert breaker.is_open("openai")
    cache.now += 299
    assert breaker.is_open("openai")
    cache.now += 2
    assert not breaker.is_open("openai")


def test_fewer_than_three_do_not_open_it(breaker):
    refuse(breaker, times=2)

    assert not breaker.is_open("openai")


@pytest.mark.parametrize("status", [429, 500, 503, 408, 400, None])
def test_only_a_refused_key_or_balance_counts(breaker, status):
    refuse(breaker, status=status, times=10)

    assert not breaker.is_open("openai")


def test_a_success_resets_the_count(breaker):
    refuse(breaker, times=2)
    breaker.record_success("openai")
    refuse(breaker, times=2)

    assert not breaker.is_open("openai")


def test_refusals_spread_over_more_than_the_cooldown_do_not_add_up(breaker, cache):
    refuse(breaker, times=2)
    cache.now += 301
    refuse(breaker, times=1)

    assert not breaker.is_open("openai")


def test_each_provider_has_its_own_breaker(breaker):
    refuse(breaker, "openai", times=3)

    assert breaker.is_open("openai") and not breaker.is_open("anthropic")

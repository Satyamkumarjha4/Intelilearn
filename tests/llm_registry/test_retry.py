"""Unit under test: `llm_registry.retry.ExponentialBackoffPolicy`, which decides whether a failed model call is worth
retrying on the same model and how long to wait first.

Why: retrying a fatal error (bad key, unknown model) wastes the time budget before the fallback model is tried, while
not retrying a 429 or timeout throws away a model that would have answered seconds later.

Use cases:
- 429, 5xx, timeouts and SDK "Timeout" classes are retryable; 4xx, a missing key and unknown errors are not
- a Retry-After header is honoured, capped at the maximum delay
- backoff doubles per attempt, with jitter and a ceiling
- waiting too long for the rate limiter is not retried
"""

import pytest

from llm_registry.providers import MissingAPIKey
from llm_registry.ratelimit import RateLimitWaitExceeded
from llm_registry.retry import ExponentialBackoffPolicy


class _Response:
    def __init__(self, status, headers=None):
        self.status_code, self.headers = status, headers or {}


class _HTTPError(Exception):
    def __init__(self, status, headers=None):
        super().__init__(f"HTTP {status}")
        self.response = _Response(status, headers)


class APITimeoutError(Exception):
    pass


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        (_HTTPError(429), True),
        (_HTTPError(503), True),
        (_HTTPError(400), False),
        (_HTTPError(404), False),
        (TimeoutError(), True),
        (APITimeoutError(), True),
        (MissingAPIKey("x"), False),
        (ValueError("weird"), False),
    ],
)
def test_error_classification(exc, retryable):
    assert ExponentialBackoffPolicy().is_retryable(exc) is retryable


def test_retry_after_header_is_honoured():
    policy = ExponentialBackoffPolicy()
    assert policy.delay(1, _HTTPError(429, {"retry-after": "7"})) == 7
    assert policy.delay(1, _HTTPError(429, {"retry-after": "999"})) == 30  # capped


def test_backoff_doubles_per_attempt_with_jitter_and_a_ceiling():
    policy = ExponentialBackoffPolicy(base_s=1.0, max_s=30.0, jitter=lambda: 1.0)  # jitter at its top: the full delay
    assert [policy.delay(n, TimeoutError()) for n in (1, 2, 3, 10)] == [1.0, 2.0, 4.0, 30.0]
    assert ExponentialBackoffPolicy(jitter=lambda: 0.0).delay(3, TimeoutError()) == 2.0  # at its bottom: half


def test_waiting_on_the_rate_limit_too_long_is_not_retried():
    assert ExponentialBackoffPolicy().is_retryable(RateLimitWaitExceeded("x")) is False

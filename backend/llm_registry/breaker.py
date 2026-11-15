"""A circuit breaker for providers that refuse the key or the balance (401, 402).

Those errors do not get better by trying again, but every call of every lesson would still try that layer first
and fail. After `failures` in a row the provider is skipped for `cooldown_s`, then tried again, so a fixed key or a
topped-up balance is picked up. Counts live in the Django cache so every worker shares them; anything else (a rate
limit, a server error, a timeout) is not a refusal and never counts.
"""

from django.core.cache import cache as default_cache

from .retry import ExponentialBackoffPolicy


class ProviderBreaker:
    REFUSED = frozenset({401, 402})

    def __init__(self, cache=None, failures: int = 3, cooldown_s: int = 300):
        self._cache = cache if cache is not None else default_cache
        self._failures, self._cooldown_s = failures, cooldown_s

    def is_open(self, provider_key: str) -> bool:
        return bool(self._cache.get(self._key("open", provider_key)))

    def record_failure(self, provider_key: str, exc: Exception) -> None:
        if ExponentialBackoffPolicy._status_code(exc) not in self.REFUSED:
            return
        count = (self._cache.get(self._key("count", provider_key)) or 0) + 1
        if count >= self._failures:
            self._cache.set(self._key("open", provider_key), True, self._cooldown_s)
            self._cache.delete(self._key("count", provider_key))
        else:
            self._cache.set(self._key("count", provider_key), count, self._cooldown_s)

    def record_success(self, provider_key: str) -> None:
        self._cache.delete(self._key("count", provider_key))

    @staticmethod
    def _key(kind: str, provider_key: str) -> str:
        return f"llm_registry:breaker:{kind}:{provider_key}"

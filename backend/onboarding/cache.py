"""The Redis cache behind the topic suggestions: whole pages, a model's topic list, and translations.

Cache-aside, and never the reason a learner is not helped: a cache that is down, or an entry in a shape this code does
not know, reads as "nothing cached" and writes do nothing.
"""

import hashlib
import logging
from collections.abc import Callable
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache as default_cache

from .domain import Slug, SuggestionRequest, Suggestions, Topic
from .router import Route

logger = logging.getLogger(__name__)


class SuggestionCache:
    VERSION = "v1"
    READABLE_MAX = 100

    def __init__(self, cache=None, ttl_s: int | None = None):
        self._cache = cache if cache is not None else default_cache
        self._ttl_s = ttl_s if ttl_s is not None else settings.ONBOARDING_SUGGESTION_TTL_S

    def get_response(self, request: SuggestionRequest, route: Route) -> Suggestions | None:
        return self._read(self._response_key(request, route), Suggestions.from_dict)

    def put_response(self, request: SuggestionRequest, route: Route, suggestions: Suggestions) -> None:
        self._write(self._response_key(request, route), suggestions.as_dict())

    def get_topics(self, request: SuggestionRequest, route: Route) -> list[Topic] | None:
        return self._read(self._topics_key(request, route), lambda raw: [Topic.from_dict(item) for item in raw])

    def put_topics(self, request: SuggestionRequest, route: Route, topics: list[Topic]) -> None:
        self._write(self._topics_key(request, route), [topic.as_dict() for topic in topics])

    def get_translation(self, language: str, text: str) -> str | None:
        return self._read(self._translation_key(language, text), self._text)

    def put_translation(self, language: str, text: str, translated: str) -> None:
        self._write(self._translation_key(language, text), translated)

    # --- keys: normalised, plain text, bounded ----------------------------------------------------------------------

    def _context(self, request: SuggestionRequest, route: Route) -> str:
        """Readable when short and plain (easy to find in Redis); otherwise the free text is replaced by its hash, so
        the key stays short and safe whatever a learner typed."""
        text = ":".join([Slug.of(request.grade_label), route.key])
        if text.isascii() and len(text) <= self.READABLE_MAX:
            free = quote(text, safe="-:")
        else:
            free = "h" + hashlib.sha1(text.encode()).hexdigest()[:20]
        fixed = [request.education_level, request.goal, request.preferred_language]
        return ":".join([quote(fixed[0], safe=""), free, *(quote(part, safe="") for part in fixed[1:])])

    def _response_key(self, request: SuggestionRequest, route: Route) -> str:
        return f"onboarding:{self.VERSION}:response:{self._context(request, route)}:{request.page}"

    def _topics_key(self, request: SuggestionRequest, route: Route) -> str:
        return f"onboarding:{self.VERSION}:topics:{self._context(request, route)}"

    def _translation_key(self, language: str, text: str) -> str:
        digest = hashlib.sha1(text.encode()).hexdigest()[:20]
        return f"onboarding:{self.VERSION}:translation:{quote(language, safe='')}:{digest}"

    # --- reading and writing, quietly ---------------------------------------------------------------------------------

    def _read(self, key: str, parse: Callable):
        try:
            raw = self._cache.get(key)
            return None if raw is None else parse(raw)
        except Exception as exc:  # the cache is down, or the entry is not what this version writes
            logger.warning("onboarding cache read failed: %s", type(exc).__name__)
            return None

    def _write(self, key: str, value) -> None:
        try:
            self._cache.set(key, value, timeout=self._ttl_s)
        except Exception as exc:
            logger.warning("onboarding cache write failed: %s", type(exc).__name__)

    @staticmethod
    def _text(raw) -> str:
        if not isinstance(raw, str):
            raise TypeError("a translation is text")
        return raw

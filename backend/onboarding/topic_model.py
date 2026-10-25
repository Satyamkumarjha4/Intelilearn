"""The one place onboarding talks to a model: the `TopicModel` port and its gateway-backed implementation."""

import logging
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

from llm_registry.gateway import Gateway
from llm_registry.ratelimit import CacheWindowRateLimiter
from llm_registry.resolver import RegistryResolver

from .domain import SuggestionRequest, Topic
from .prompts import SuggestTopicsPrompt, TranslateTopicsPrompt
from .schemas import SuggestedTopic, TopicSuggestions

logger = logging.getLogger(__name__)


class TopicModelError(RuntimeError):
    """Anything that stopped a model from giving usable topics. The service answers with the catalogue instead."""


class TopicModel(Protocol):
    """Raises only `TopicModelError`; a returned list is never empty."""

    def suggest(self, request: SuggestionRequest) -> list[Topic]:
        """At least four topics for this learner, titled in their language."""

    def translate(self, language: str, topics: Sequence[Topic]) -> list[Topic]:
        """The same topics, in the same order, with title, subject and reason in `language`."""


class GatewayTopicModel:
    """`onboarding.suggest_topics` through the gateway, with the registry's current models (no lesson is involved, so
    the snapshot is taken now)."""

    NODE = "onboarding.suggest_topics"
    MIN_TOPICS = 4
    # A learner is waiting: when a provider's per-minute budget is spent, give up and let the next model (or the
    # catalogue) answer instead of sleeping until the window turns over, as the lesson flow does.
    RATE_WAIT_S = 1

    def __init__(self, gateway: Gateway | None = None, snapshots: RegistryResolver | None = None):
        self._gateway = gateway if gateway is not None else self.default_gateway()
        self._snapshots = snapshots if snapshots is not None else RegistryResolver()

    @classmethod
    def default_gateway(cls) -> Gateway:
        return Gateway(limiter=CacheWindowRateLimiter(max_wait_s=cls.RATE_WAIT_S))

    def suggest(self, request: SuggestionRequest) -> list[Topic]:
        reply = self._ask(SuggestTopicsPrompt().messages({"request": request}))
        topics = self._clean(reply.topics)
        if len(topics) < self.MIN_TOPICS:
            raise TopicModelError(f"the model gave {len(topics)} usable topics; at least {self.MIN_TOPICS} are needed")
        return topics

    def translate(self, language: str, topics: Sequence[Topic]) -> list[Topic]:
        reply = self._ask(TranslateTopicsPrompt().messages({"language": language, "topics": list(topics)}))
        if len(reply.topics) != len(topics):
            raise TopicModelError(f"expected {len(topics)} topics, got {len(reply.topics)}")
        return [
            replace(original, title=item.title.strip(), subject=item.subject.strip(), reason=item.reason.strip())
            for original, item in zip(topics, reply.topics, strict=True)
        ]

    def _ask(self, messages) -> TopicSuggestions:
        try:
            result = self._gateway.invoke(
                self.NODE, messages, snapshot=self._snapshots.snapshot(), schema=TopicSuggestions
            )
            return result.output
        except Exception as exc:  # every model failed, a rate limit, a timeout, a node missing from the registry...
            logger.warning("onboarding topic model failed: %s", type(exc).__name__)
            raise TopicModelError(f"{type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _clean(raw: list[SuggestedTopic]) -> list[Topic]:
        topics, seen = [], set()
        for item in raw:
            title = item.title.strip()
            if not title or title.casefold() in seen:
                continue
            seen.add(title.casefold())
            topics.append(Topic(title, item.title_en.strip() or title, item.subject.strip(), item.reason.strip()))
        return topics

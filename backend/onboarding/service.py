"""Answers "which four topics should this learner start with?": the catalogue first, a model only where the catalogue
cannot, and the English catalogue again whenever a model cannot answer. Never raises for a model's sake."""

import logging

from .cache import SuggestionCache
from .catalogue import Catalogue
from .domain import Source, SuggestionRequest, Suggestions, Topic
from .pager import Pager
from .reasons import ReasonBuilder
from .router import Route, TopicRouter
from .topic_model import GatewayTopicModel, TopicModel, TopicModelError
from .translation import TopicTranslator

logger = logging.getLogger(__name__)


class TopicSuggester:
    def __init__(
        self,
        router: TopicRouter,
        reasons: ReasonBuilder,
        model: TopicModel,
        cache: SuggestionCache,
        translator: TopicTranslator | None = None,
    ):
        self._router, self._reasons, self._model, self._cache = router, reasons, model, cache
        self._translator = translator if translator is not None else TopicTranslator(model, cache)

    @classmethod
    def default(cls) -> "TopicSuggester":
        """The composition root: the shipped catalogue, the gateway-backed model and the Redis cache."""
        return cls(TopicRouter(Catalogue.default()), ReasonBuilder(), GatewayTopicModel(), SuggestionCache())

    def suggest(self, request: SuggestionRequest) -> Suggestions:
        route = self._router.route(request)
        if (cached := self._cache.get_response(request, route)) is not None:
            return cached
        suggestions = self._answer(request, route)
        if suggestions.source is not Source.FALLBACK:  # a failure is not remembered for 30 days
            self._cache.put_response(request, route, suggestions)
        return suggestions

    def _answer(self, request: SuggestionRequest, route: Route) -> Suggestions:
        try:
            return self._from_catalogue(request, route) if route.matched else self._from_model(request, route)
        except TopicModelError as exc:
            logger.warning("onboarding suggestions fell back to the catalogue: %s", exc)
            return self._english_catalogue(request, route, Source.FALLBACK)

    def _from_catalogue(self, request: SuggestionRequest, route: Route) -> Suggestions:
        english = self._english_catalogue(request, route, Source.CATALOGUE)
        if request.english:
            return english
        topics = self._translator.translate(request.preferred_language, list(english.topics))
        return Suggestions(Source.CATALOGUE, tuple(topics), english.has_more)

    def _from_model(self, request: SuggestionRequest, route: Route) -> Suggestions:
        topics = self._cache.get_topics(request, route)
        if topics is None:
            topics = self._model.suggest(request)
            self._cache.put_topics(request, route, topics)
        return Suggestions(Source.AI, tuple(Pager.page(topics, request.page)), Pager.has_more(topics))

    def _english_catalogue(self, request: SuggestionRequest, route: Route, source: Source) -> Suggestions:
        reason = self._reasons.reason(request)
        items = list(route.items)
        topics = tuple(Topic(item.title, item.title, item.subject, reason) for item in Pager.page(items, request.page))
        return Suggestions(source, topics, Pager.has_more(items))

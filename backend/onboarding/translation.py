from dataclasses import replace

from .cache import SuggestionCache
from .domain import Topic
from .topic_model import TopicModel


class TopicTranslator:
    """Puts topics in another language, paying for each piece of text once: titles, subjects and reasons are cached per
    (language, English text), and one batched model call covers the topics that still have something missing."""

    def __init__(self, model: TopicModel, cache: SuggestionCache):
        self._model, self._cache = model, cache

    def translate(self, language: str, topics: list[Topic]) -> list[Topic]:
        """Raises `TopicModelError` when the model cannot translate what is missing."""
        missing = [
            t for t in topics if any(self._cache.get_translation(language, text) is None for text in self._texts(t))
        ]
        fresh: dict[str, Topic] = {}
        if missing:
            for english, translated in zip(missing, self._model.translate(language, missing), strict=True):
                fresh[english.title_en] = translated
                for source, text in zip(self._texts(english), self._texts(translated, english=False), strict=True):
                    self._cache.put_translation(language, source, text)
        # What the model has just said is used as it is: the cache may be unable to hold it, and that is no reason to
        # hand the learner English.
        return [fresh.get(topic.title_en) or self._from_cache(language, topic) for topic in topics]

    @staticmethod
    def _texts(topic: Topic, *, english: bool = True) -> tuple[str, str, str]:
        """The three pieces that are translated: the title (the English one is the key), the subject and the reason."""
        return (topic.title_en if english else topic.title, topic.subject, topic.reason)

    def _from_cache(self, language: str, topic: Topic) -> Topic:
        def pick(text: str) -> str:
            return self._cache.get_translation(language, text) or text  # an entry that vanished reads as English

        return replace(topic, title=pick(topic.title_en), subject=pick(topic.subject), reason=pick(topic.reason))

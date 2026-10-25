"""Unit under test: `onboarding.translation.TopicTranslator`, which puts catalogue topics in the learner's language and
pays for each piece of text once.

Why: translating is the one model call a catalogue answer can need, and the same titles are asked for in the same
language by many learners. Cached pieces must not be sent again, what is sent must come back as a whole page, and a
cache that cannot keep (or has lost) a piece must never turn into English for the learner or into an error.

Use cases:
- uncached topics are translated in one call and each piece is cached per language and English text
- topics whose title, subject and reason are all cached are not sent; a topic with one piece missing is sent whole
- what the model has just translated is used as it is, even if the cache cannot store it
- a piece that vanished from the cache between the check and the read reads as its English text
- a model that cannot translate raises its error and caches nothing
"""

import pytest
from support.fakes import FakeTopicModel

from onboarding.cache import SuggestionCache
from onboarding.domain import Topic
from onboarding.topic_model import TopicModelError
from onboarding.translation import TopicTranslator


class Forgetful:
    """A cache that answers once per key and then has lost it."""

    def __init__(self):
        self.items, self.asked = {}, set()

    def get(self, key, default=None):
        if key in self.asked:
            return None
        self.asked.add(key)
        return self.items.get(key)

    def set(self, key, value, timeout=None):
        self.items[key] = value


def topic(name):
    return Topic(name, name, "Maths", f"Why {name}")


def test_uncached_topics_go_out_in_one_call_and_each_piece_is_cached():
    model, cache = FakeTopicModel(), SuggestionCache()

    result = TopicTranslator(model, cache).translate("hi", [topic("A"), topic("B")])

    assert len(model.translated) == 1 and [t.title_en for t in model.translated[0][1]] == ["A", "B"]
    assert [t.title for t in result] == ["[hi] A", "[hi] B"]
    assert [cache.get_translation("hi", text) for text in ("A", "Maths", "Why A")] == [
        "[hi] A",
        "[hi] Maths",
        "[hi] Why A",
    ]


def test_fully_cached_topics_are_not_sent_and_a_partly_cached_one_is_sent_whole():
    model, cache = FakeTopicModel(), SuggestionCache()
    translator = TopicTranslator(model, cache)
    translator.translate("hi", [topic("A")])
    model.translated.clear()

    translator.translate("hi", [topic("A"), topic("B")])

    assert [t.title_en for t in model.translated[0][1]] == ["B"]  # A was cached, so only B went out
    model.translated.clear()
    changed_reason = Topic("A", "A", "Maths", "A new reason")  # title and subject cached, reason not

    translator.translate("hi", [changed_reason])

    assert model.translated[0][1] == [changed_reason]
    model.translated.clear()
    translator.translate("hi", [topic("A"), topic("B"), changed_reason])
    assert model.translated == []


def test_a_fresh_translation_is_used_even_if_the_cache_cannot_hold_it():
    class Unwritable:
        def get(self, key, default=None):
            return None

        def set(self, key, value, timeout=None):
            raise ConnectionError("read-only")

    result = TopicTranslator(FakeTopicModel(), SuggestionCache(Unwritable())).translate("hi", [topic("A")])

    assert result[0].title == "[hi] A"


def test_a_piece_that_vanished_from_the_cache_reads_as_english():
    cache = SuggestionCache(Forgetful())
    for text in ("A", "Maths", "Why A"):
        cache.put_translation("hi", text, f"[hi] {text}")

    result = TopicTranslator(FakeTopicModel(), cache).translate(
        "hi", [topic("A")]
    )  # present for the check, gone for the read

    assert (result[0].title, result[0].subject, result[0].reason) == ("A", "Maths", "Why A")


def test_a_model_that_cannot_translate_raises_and_caches_nothing():
    model, cache = FakeTopicModel().script_translate(TopicModelError("timeout")), SuggestionCache()

    with pytest.raises(TopicModelError):
        TopicTranslator(model, cache).translate("hi", [topic("A")])

    assert cache.get_translation("hi", "A") is None

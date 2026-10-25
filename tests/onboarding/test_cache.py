"""Unit under test: `onboarding.cache.SuggestionCache`, the Redis cache of whole suggestion pages, of a model's topic
list and of translations.

Why: a model call is the slow, paid step, and the same few combinations (class, goal, language) are asked for by many
learners; the cache is what makes onboarding instant and free after the first. Its key decides who shares an entry, so
two spellings of one answer must share it and two different answers must not. And it must never be the thing that fails:
Redis being down must look like an empty cache.

Use cases:
- one answer spelled differently (a class as "Class 9", "9th" or "grade 9"; a field in other case or spacing) is one key
- a different page, language, goal, level, class, family or field is a different key; the model's topic list is shared
  by every page
- keys are plain text without spaces or odd characters and stay short, whatever the learner typed
- a page, a topic list and a translation are stored and read back as they were, for the configured time (30 days by
  default)
- a missing entry, an entry in the wrong shape, and a cache that raises on read or write are all just "nothing cached"
"""

import pytest

from onboarding.cache import SuggestionCache
from onboarding.catalogue import Catalogue
from onboarding.domain import Source, SuggestionRequest, Suggestions, Topic
from onboarding.router import TopicRouter

router = TopicRouter(Catalogue.default())
TOPIC = Topic("भिन्न", "Fractions", "गणित", "कक्षा 6")


class RecordingCache:
    def __init__(self):
        self.items, self.timeouts = {}, {}

    def get(self, key, default=None):
        return self.items.get(key, default)

    def set(self, key, value, timeout=None):
        self.items[key], self.timeouts[key] = value, timeout


class BrokenCache:
    def get(self, key, default=None):
        raise ConnectionError("redis is down")

    def set(self, key, value, timeout=None):
        raise ConnectionError("redis is down")


def ask(**fields):
    request = SuggestionRequest(**{"education_level": "school", "goal": "exam_prep", **fields})
    return request, router.route(request)


def response_key(**fields):
    cache = RecordingCache()
    SuggestionCache(cache).put_response(*ask(**fields), Suggestions(Source.CATALOGUE, (TOPIC,), True))
    (key,) = cache.items
    return key


def topics_key(**fields):
    cache = RecordingCache()
    SuggestionCache(cache).put_topics(*ask(**fields), [TOPIC])
    (key,) = cache.items
    return key


def test_one_answer_spelled_differently_is_one_key():
    assert (
        response_key(grade_or_year="Class 9")
        == response_key(grade_or_year="9th")
        == response_key(grade_or_year="grade 9")
    )
    undergraduate = {"education_level": "undergraduate"}
    assert response_key(**undergraduate, field_of_study="Architecture") == response_key(
        **undergraduate, field_of_study="  ARCHITECTURE "
    )


@pytest.mark.parametrize(
    "other",
    [
        {"page": 1},
        {"preferred_language": "hi"},
        {"goal": "deep_understanding"},
        {"grade_or_year": "Class 10"},
        {"education_level": "undergraduate"},
        {"education_level": "undergraduate", "field_of_study": "Physics"},
        {"education_level": "undergraduate", "field_of_study": "Architecture"},
        {"education_level": "postgraduate", "field_of_study": "Physics"},
    ],
)
def test_a_different_answer_is_a_different_key(other):
    assert response_key(**other) != response_key(grade_or_year="9")


def test_the_models_topic_list_is_shared_by_every_page():
    fields = {"education_level": "undergraduate", "field_of_study": "Architecture"}

    assert topics_key(**fields, page=0) == topics_key(**fields, page=5)
    assert topics_key(**fields) != topics_key(**fields, preferred_language="hi")


def test_keys_are_plain_text_and_short():
    for key in (
        response_key(
            education_level="undergraduate", field_of_study="घर बनाना " + "x y\n\t" * 200, grade_or_year="y" * 100
        ),
        topics_key(education_level="undergraduate", field_of_study="a b\nc" * 100),
    ):
        assert key.isascii() and " " not in key and "\n" not in key
        assert len(key) < 250


def test_a_page_a_topic_list_and_a_translation_are_stored_and_read_back_for_the_ttl():
    cache = RecordingCache()
    store = SuggestionCache(cache, ttl_s=123)
    request, route = ask(education_level="undergraduate", field_of_study="Architecture", preferred_language="hi")
    page = Suggestions(Source.AI, (TOPIC,), has_more=False)

    store.put_response(request, route, page)
    store.put_topics(request, route, [TOPIC, TOPIC])
    store.put_translation("hi", "Fractions", "भिन्न")

    assert store.get_response(request, route) == page
    assert store.get_topics(request, route) == [TOPIC, TOPIC]
    assert store.get_translation("hi", "Fractions") == "भिन्न"
    assert store.get_translation("es", "Fractions") is None  # per language
    assert set(cache.timeouts.values()) == {123}


def test_the_ttl_defaults_to_the_setting(settings):
    settings.ONBOARDING_SUGGESTION_TTL_S = 77
    cache = RecordingCache()

    SuggestionCache(cache).put_translation("hi", "Fractions", "भिन्न")

    assert set(cache.timeouts.values()) == {77}


def test_the_ttl_is_thirty_days_unless_configured(settings):
    assert settings.ONBOARDING_SUGGESTION_TTL_S == 30 * 24 * 3600


def test_nothing_cached_is_nothing():
    store = SuggestionCache(RecordingCache())
    request, route = ask()

    assert store.get_response(request, route) is None
    assert store.get_topics(request, route) is None
    assert store.get_translation("hi", "Fractions") is None


def test_an_entry_in_the_wrong_shape_is_nothing_cached():
    cache = RecordingCache()
    store = SuggestionCache(cache)
    request, route = ask()
    store.put_response(request, route, Suggestions(Source.CATALOGUE, (TOPIC,), True))
    (key,) = cache.items
    cache.items[key] = {"source": "catalogue", "topics": "nope"}
    cache.items[key.replace("response", "topics")] = [{"title": "x"}]
    cache.items[key.replace("response", "translation")] = 42

    assert store.get_response(request, route) is None
    assert store.get_topics(request, route) is None


def test_a_cache_that_raises_looks_like_an_empty_one():
    store = SuggestionCache(BrokenCache())
    request, route = ask()

    assert store.get_response(request, route) is None
    assert store.get_topics(request, route) is None
    assert store.get_translation("hi", "Fractions") is None
    store.put_response(request, route, Suggestions(Source.CATALOGUE, (TOPIC,), True))  # no error
    store.put_topics(request, route, [TOPIC])
    store.put_translation("hi", "Fractions", "भिन्न")

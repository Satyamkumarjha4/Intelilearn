"""Unit under test: `onboarding.service.TopicSuggester`, which answers "which four topics should this learner start
with?" from the catalogue, a model, or the catalogue again when a model cannot.

Why: onboarding must never wait on, or break because of, a model. The catalogue answers at once and for free; a model is
asked only for a field the catalogue does not know, or to translate; anything that goes wrong leaves the learner with
English catalogue topics, never an error. And what is paid for once (a model's list, a translation) must not be paid
for again.

Use cases:
- English, known answers: four catalogue topics with the rule-built reason, source "catalogue", no model call
- paging: the next page is the next four, pages wrap, and has_more says whether the list is longer than four
- another language: the four titles, subjects and reasons are translated in one batched call, the English titles are
  kept, and the source is still "catalogue"
- a translation that fails or comes back wrong gives the English topics with source "fallback"
- translations are cached per language and text: the same topics asked again, or another page that shares some, do not
  go to the model for what it already translated
- a field the catalogue does not know asks the model (source "ai"); the model's list is cached, so every page of it
  comes from one call, and has_more follows its length
- no field, or one without letters, is not "unknown": the general list, no model
- a model that fails gives the general list for the level, in English, source "fallback"
- fallback answers are not cached (the next request tries again); catalogue and AI answers are, and a hit never reaches
  the model
- a cache that is down changes nothing for the learner
"""

import json

import pytest

from onboarding.cache import SuggestionCache
from onboarding.catalogue import CATALOGUE_PATH, Catalogue
from onboarding.domain import Source, SuggestionRequest, Topic
from onboarding.reasons import ReasonBuilder
from onboarding.router import TopicRouter
from onboarding.service import TopicSuggester
from onboarding.topic_model import TopicModelError

catalogue = Catalogue.default()


class BrokenCache:
    def get(self, key, default=None):
        raise ConnectionError("down")

    def set(self, key, value, timeout=None):
        raise ConnectionError("down")


@pytest.fixture
def model():
    from support.fakes import FakeTopicModel

    return FakeTopicModel()


@pytest.fixture
def suggester(model):
    return TopicSuggester(TopicRouter(catalogue), ReasonBuilder(), model, SuggestionCache())


def ask(**fields):
    return SuggestionRequest(**{"education_level": "school", "goal": "exam_prep", "grade_or_year": "Class 9", **fields})


def titles(result):
    return [t.title_en for t in result.topics]


def ai_topics(*names):
    return [Topic(n, n, "Design", f"Why {n}") for n in names]


UNKNOWN = {"education_level": "undergraduate", "field_of_study": "Architecture", "grade_or_year": ""}


def test_english_known_answers_come_from_the_catalogue_without_a_model(suggester, model):
    result = suggester.suggest(ask())

    class_9 = [item.title for item in catalogue.school(9)]
    assert result.source is Source.CATALOGUE
    assert titles(result) == class_9[:4]
    assert [t.title for t in result.topics] == class_9[:4]
    assert {t.reason for t in result.topics} == {"Class 9 · often in exams"}
    assert result.topics[0].subject == catalogue.school(9)[0].subject
    assert result.has_more is True
    assert (model.suggested, model.translated) == ([], [])


def test_the_next_page_is_the_next_four_and_pages_wrap(suggester):
    class_9 = [item.title for item in catalogue.school(9)]  # ten topics

    assert titles(suggester.suggest(ask(page=1))) == class_9[4:8]
    assert titles(suggester.suggest(ask(page=2))) == class_9[8:] + class_9[:2]
    assert titles(suggester.suggest(ask(page=5))) == class_9[:4]  # 5 pages of four is two laps of ten


def test_a_list_of_four_or_fewer_has_nothing_more(model):
    data = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    data["professional"] = data["professional"][:4]
    suggester = TopicSuggester(TopicRouter(Catalogue(data)), ReasonBuilder(), model, SuggestionCache())

    result = suggester.suggest(SuggestionRequest("professional", "deep_understanding"))

    assert len(result.topics) == 4 and result.has_more is False


def test_another_language_is_translated_in_one_batched_call_keeping_the_english_titles(suggester, model):
    result = suggester.suggest(ask(preferred_language="hi"))

    assert result.source is Source.CATALOGUE
    assert len(model.translated) == 1
    language, sent = model.translated[0]
    assert language == "hi" and len(sent) == 4 and all(t.title == t.title_en for t in sent)
    assert [t.title for t in result.topics] == [f"[hi] {t.title_en}" for t in result.topics]
    assert titles(result) == [item.title for item in catalogue.school(9)][:4]
    assert result.topics[0].reason == "[hi] Class 9 · often in exams"


def test_a_translation_that_fails_gives_english_topics_as_a_fallback(suggester, model):
    model.script_translate(TopicModelError("timeout"))

    result = suggester.suggest(ask(preferred_language="hi"))

    assert result.source is Source.FALLBACK
    assert [t.title for t in result.topics] == [item.title for item in catalogue.school(9)][:4]
    assert result.topics[0].reason == "Class 9 · often in exams"


def test_translations_are_cached_per_language_and_text(suggester, model):
    suggester.suggest(ask(preferred_language="hi", page=0))
    suggester.suggest(ask(preferred_language="hi", page=0, goal="deep_understanding"))  # same titles, another reason
    sent_second = model.translated[1][1]

    assert len(model.translated) == 2
    assert all(t.reason != "Class 9 · often in exams" for t in sent_second)  # only what was new went out ...
    suggester.suggest(ask(preferred_language="hi", page=0, goal="deep_understanding"))
    suggester.suggest(ask(preferred_language="hi", page=0))
    assert len(model.translated) == 2  # ... and a repeat of either asks for nothing
    suggester.suggest(ask(preferred_language="es", page=0))
    assert len(model.translated) == 3  # another language is another translation


def test_a_field_the_catalogue_does_not_know_asks_the_model_once_for_all_pages(suggester, model):
    model.script_suggest(ai_topics("A", "B", "C", "D", "E", "F"))

    first = suggester.suggest(ask(**UNKNOWN))
    second = suggester.suggest(ask(**UNKNOWN, page=1))

    assert first.source is second.source is Source.AI
    assert titles(first) == list("ABCD") and titles(second) == ["E", "F", "A", "B"]
    assert first.has_more and second.has_more
    assert first.topics[0].reason == "Why A"  # the model's own reason
    assert len(model.suggested) == 1
    assert model.suggested[0].field_of_study == "Architecture"


def test_an_ai_list_of_four_has_nothing_more(suggester, model):
    model.script_suggest(ai_topics("A", "B", "C", "D"))

    assert suggester.suggest(ask(**UNKNOWN)).has_more is False


@pytest.mark.parametrize("field", ["", "  ", "???"])
def test_no_field_is_not_an_unknown_field(suggester, model, field):
    result = suggester.suggest(ask(**{**UNKNOWN, "field_of_study": field}))

    assert result.source is Source.CATALOGUE
    assert titles(result) == [item.title for item in catalogue.general("undergraduate")][:4]
    assert model.suggested == []


def test_a_model_that_fails_gives_the_general_list_in_english_as_a_fallback(suggester, model):
    model.script_suggest(TopicModelError("every model failed"))

    result = suggester.suggest(ask(**UNKNOWN, preferred_language="hi"))

    assert result.source is Source.FALLBACK
    assert titles(result) == [item.title for item in catalogue.general("undergraduate")][:4]
    assert [t.title for t in result.topics] == titles(result)  # English, though Hindi was asked for
    assert model.translated == []


def test_fallback_answers_are_not_cached_and_the_next_request_tries_again(suggester, model):
    model.script_suggest(TopicModelError("down"), ai_topics("A", "B", "C", "D"))

    assert suggester.suggest(ask(**UNKNOWN)).source is Source.FALLBACK
    assert suggester.suggest(ask(**UNKNOWN)).source is Source.AI
    assert len(model.suggested) == 2


class NoModel:
    def suggest(self, request):
        raise AssertionError("the model must not be asked")

    def translate(self, language, topics):
        raise AssertionError("the model must not be asked")


@pytest.mark.parametrize("fields", [UNKNOWN, {"preferred_language": "hi"}], ids=["an AI list", "a translated page"])
def test_a_cache_hit_never_reaches_the_model(model, fields):
    cache = SuggestionCache()
    model.script_suggest(ai_topics("A", "B", "C", "D", "E"))
    answer = TopicSuggester(TopicRouter(catalogue), ReasonBuilder(), model, cache).suggest(ask(**fields))

    again = TopicSuggester(TopicRouter(catalogue), ReasonBuilder(), NoModel(), cache).suggest(ask(**fields))

    assert again == answer


def test_a_cache_that_is_down_changes_nothing_for_the_learner(model):
    suggester = TopicSuggester(TopicRouter(catalogue), ReasonBuilder(), model, SuggestionCache(BrokenCache()))
    model.script_suggest(ai_topics("A", "B", "C", "D"))

    assert suggester.suggest(ask()).source is Source.CATALOGUE
    assert suggester.suggest(ask(**UNKNOWN)).source is Source.AI
    hindi = suggester.suggest(ask(preferred_language="hi"))
    assert hindi.source is Source.CATALOGUE
    assert all(
        t.title.startswith("[hi] ") for t in hindi.topics
    )  # the translation is used even though it cannot be stored

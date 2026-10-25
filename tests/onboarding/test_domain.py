"""Unit under test: `onboarding.domain` (`SuggestionRequest`, `GradeParser`, `Slug`, `Topic`, `Suggestions`), the plain
values of the topic suggestions.

Why: learners type their class, year and field of study in their own words ("Class 9", "9th", "grade 9, CBSE"). Every
later step (the catalogue list, the reason text, the cache key) leans on reading those the same way, so two spellings
of one class must give one list and one cache entry, and nothing a learner types may break a key.

Use cases:
- a school class is read from the usual spellings, only when it is a class the catalogue covers (6 to 12)
- the reason's label is "Class 9" for a school class, the learner's own words otherwise, and empty when they gave none
- the field of study becomes a short slug (lower case, words joined by dashes, any script, bounded length), and a field
  with no letters at all is as good as none
- English is the default language and is recognised
- a topic and a result turn into the API's shape
"""

import pytest

from onboarding.domain import GradeParser, Slug, Source, SuggestionRequest, Suggestions, Topic


def request(**fields):
    return SuggestionRequest(**{"education_level": "school", "goal": "exam_prep", **fields})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Class 9", 9),
        ("9th", 9),
        ("grade 12", 12),
        ("Std. 6 (CBSE)", 6),
        ("11", 11),
        ("class 10 science", 10),
        ("Class 5", None),
        ("Class 13", None),
        ("2nd year B.Tech", None),
        ("", None),
        ("   ", None),
        ("nine", None),
    ],
)
def test_a_school_class_is_read_from_the_usual_spellings(text, expected):
    assert GradeParser.parse(text) == expected
    assert request(grade_or_year=text).school_class == expected


def test_only_a_school_learner_has_a_school_class():
    assert request(education_level="undergraduate", grade_or_year="Class 9").school_class is None


def test_the_reason_label_is_the_class_for_school_and_their_own_words_otherwise():
    assert request(grade_or_year="9th").grade_label == "Class 9"
    assert request(grade_or_year="  Std 5  ").grade_label == "Std 5"
    assert request(education_level="undergraduate", grade_or_year=" 2nd year B.Tech ").grade_label == "2nd year B.Tech"
    assert request().grade_label == ""


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Computer Science", "computer-science"),
        ("  B.Tech -- CSE!! ", "b-tech-cse"),
        ("Médecine générale", "médecine-générale"),
        ("कंप्यूटर विज्ञान", "कंप्यूटर-विज्ञान"),
        ("", ""),
        ("!!!", ""),
    ],
)
def test_the_field_becomes_a_safe_slug(text, slug):
    assert Slug.of(text) == slug
    assert request(field_of_study=text).field_slug == slug


def test_a_field_without_letters_counts_as_none():
    assert request(field_of_study="???").has_field is False
    assert request(field_of_study="B.Tech").has_field is True
    assert request().has_field is False


def test_a_slug_is_bounded():
    assert len(Slug.of("x" * 500)) == Slug.MAX_LENGTH


def test_english_is_the_default_language():
    assert request().english
    assert not request(preferred_language="hi").english


def test_a_topic_and_a_result_turn_into_the_apis_shape():
    topic = Topic(title="भिन्न", title_en="Fractions", subject="गणित", reason="कक्षा 6")

    assert topic.as_dict() == {"title": "भिन्न", "title_en": "Fractions", "subject": "गणित", "reason": "कक्षा 6"}
    assert Suggestions(Source.AI, (topic,), has_more=True).as_dict() == {
        "source": "ai",
        "topics": [topic.as_dict()],
        "has_more": True,
    }

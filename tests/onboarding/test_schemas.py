"""Unit under test: `onboarding.schemas` (`SuggestedTopic`, `TopicSuggestions`), the structured output the topic node
returns.

Why: the schema is what the model is held to. If it let through an empty title, a whole paragraph, or fewer topics
than a page, the learner would see it; if it were stricter than the model can manage, every call would fail over to
the catalogue.

Use cases:
- a topic needs a title, an English title, a subject and a reason, each within a sensible length
- a reply holds four to eight topics (six to eight asked for; four is what a translated page has)
- an empty or over-long field, or too few or too many topics, is refused
"""

import pytest
from pydantic import ValidationError

from onboarding.schemas import SuggestedTopic, TopicSuggestions


def topic(**fields):
    return {
        "title": "Binary search",
        "title_en": "Binary search",
        "subject": "Algorithms",
        "reason": "Common in interviews",
        **fields,
    }


def test_a_complete_topic_is_accepted():
    assert SuggestedTopic.model_validate(topic()).subject == "Algorithms"


@pytest.mark.parametrize(
    "bad",
    [
        {"title": ""},
        {"title": "x" * 121},
        {"subject": ""},
        {"subject": "x" * 61},
        {"reason": ""},
        {"reason": "x" * 161},
        {"title_en": "x" * 121},
    ],
)
def test_an_empty_or_over_long_field_is_refused(bad):
    with pytest.raises(ValidationError):
        SuggestedTopic.model_validate(topic(**bad))


@pytest.mark.parametrize("count", [4, 6, 8])
def test_four_to_eight_topics_are_accepted(count):
    assert (
        len(TopicSuggestions.model_validate({"topics": [topic(title=f"T{n}") for n in range(count)]}).topics) == count
    )


@pytest.mark.parametrize("count", [0, 3, 9])
def test_too_few_or_too_many_topics_are_refused(count):
    with pytest.raises(ValidationError):
        TopicSuggestions.model_validate({"topics": [topic() for _ in range(count)]})

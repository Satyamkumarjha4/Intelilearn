"""Unit under test: `onboarding.topic_model.GatewayTopicModel`, the `TopicModel` port backed by the
`onboarding.suggest_topics` node through the gateway.

Why: this is the only place onboarding talks to a model. Whatever goes wrong there (every model failing, a rate limit,
a timeout, a reply of the wrong size, the node not even configured) has to come out as one error the service knows to
answer with the catalogue, and nothing here may make a learner wait on a busy provider.

Use cases:
- suggest: calls the node with the registry snapshot and the TopicSuggestions schema, and returns clean topics (English
  title filled in when the model left it out, blanks and repeated titles dropped, whitespace trimmed)
- suggest: fewer than four usable topics is an error, since a page is four
- translate: returns the topics in the language, in order, keeping each English title the catalogue gave
- translate: a reply with a different number of topics is an error
- any failure of the gateway or the snapshot (every model failed, a node missing from the registry, a bad reply) is a
  `TopicModelError`, and the cause is kept
- the default gateway waits at most a second for a rate limit instead of the lesson flow's two minutes
"""

import pytest
from support.fakes import FakeGateway

from llm_registry.gateway import AllModelsFailed
from onboarding.domain import SuggestionRequest, Topic
from onboarding.schemas import TopicSuggestions
from onboarding.topic_model import GatewayTopicModel, TopicModelError

NODE = "onboarding.suggest_topics"
SNAPSHOT = {"version": 1, "nodes": {NODE: {}}}


class Snapshots:
    def snapshot(self):
        return SNAPSHOT


def reply(*titles, language_titles=None):
    return {
        "topics": [
            {"title": (language_titles or {}).get(t, t), "title_en": t, "subject": "Maths", "reason": f"Why {t}"}
            for t in titles
        ]
    }


def model(gateway):
    return GatewayTopicModel(gateway=gateway, snapshots=Snapshots())


request = SuggestionRequest("undergraduate", "exam_prep", field_of_study="Architecture")


def test_suggest_calls_the_node_and_returns_topics():
    gateway = FakeGateway({NODE: [reply("A", "B", "C", "D", "E", "F")]})

    topics = model(gateway).suggest(request)

    call = gateway.called(NODE)[0]
    assert call.schema is TopicSuggestions and call.snapshot is SNAPSHOT
    assert [t.title for t in topics] == list("ABCDEF")
    assert topics[0] == Topic("A", "A", "Maths", "Why A")


def test_suggest_cleans_what_the_model_returns():
    messy = {
        "topics": [
            {"title": "  Heat  ", "title_en": "", "subject": " Physics ", "reason": "r"},
            {"title": "heat", "title_en": "Heat", "subject": "Physics", "reason": "again"},  # same title, other case
            {"title": "Light", "title_en": "Light", "subject": "Physics", "reason": "r"},
            {"title": "Sound", "title_en": "Sound", "subject": "Physics", "reason": "r"},
            {"title": "Waves", "title_en": "Waves", "subject": "Physics", "reason": "r"},
            {"title": "Optics", "title_en": "Optics", "subject": "Physics", "reason": "r"},
        ]
    }

    topics = model(FakeGateway({NODE: [messy]})).suggest(request)

    assert [t.title for t in topics] == ["Heat", "Light", "Sound", "Waves", "Optics"]
    assert topics[0].title_en == "Heat" and topics[0].subject == "Physics"


def test_suggest_with_fewer_than_four_usable_topics_is_an_error():
    repeated = {"topics": [{"title": "Heat", "title_en": "Heat", "subject": "Physics", "reason": "r"}] * 4}

    with pytest.raises(TopicModelError, match="at least 4"):
        model(FakeGateway({NODE: [repeated]})).suggest(request)


def test_translate_returns_the_topics_in_the_language_keeping_the_english_titles():
    gateway = FakeGateway(
        {NODE: [reply("a", "b", "c", "d", language_titles={"a": "भिन्न", "b": "गति", "c": "ऊष्मा", "d": "प्रकाश"})]}
    )
    english = [Topic(t, t, "Maths", f"r{t}") for t in "wxyz"]

    translated = model(gateway).translate("hi", english)

    assert [t.title for t in translated] == ["भिन्न", "गति", "ऊष्मा", "प्रकाश"]
    assert [t.title_en for t in translated] == list("wxyz")  # the catalogue's English titles, not the model's
    assert "Hindi" in gateway.called(NODE)[0].messages[0].content


def test_translate_with_a_different_number_of_topics_back_is_an_error():
    gateway = FakeGateway({NODE: [reply("a", "b", "c", "d", "e")]})  # five back for four sent

    with pytest.raises(TopicModelError, match="expected 4 topics, got 5"):
        model(gateway).translate("hi", [Topic(t, t, "Maths", "r") for t in "wxyz"])


@pytest.mark.parametrize(
    "failure",
    [
        AllModelsFailed(NODE, ["groq/x: Timeout"]),
        KeyError("Node 'onboarding.suggest_topics' is not in the registry snapshot"),
        ValueError("bad"),
    ],
)
def test_any_gateway_failure_is_a_topic_model_error_with_its_cause(failure):
    gateway = FakeGateway({NODE: [failure, failure]})

    with pytest.raises(TopicModelError) as raised:
        model(gateway).suggest(request)
    assert raised.value.__cause__ is failure
    with pytest.raises(TopicModelError):
        model(gateway).translate("hi", [Topic("a", "a", "s", "r")] * 4)


def test_the_default_gateway_does_not_wait_out_a_rate_limit():
    assert GatewayTopicModel.default_gateway().limiter.max_wait_s == GatewayTopicModel.RATE_WAIT_S <= 1

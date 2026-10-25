"""Unit under test: `POST /api/onboarding/topic-suggestions` (`onboarding.views.TopicSuggestionsView`), the four first
topics offered on the "Where would you like to start?" step.

Why: this runs before the profile is saved, on every visit to that step, so it must accept what the form has so far,
refuse only what can never be answered, answer fast and never fail the step: a model that is down is the catalogue's
job, not an error for the learner. It is also the one onboarding call that can cost a model call, so it has a per-user
limit.

Use cases:
- it needs a signed-in learner, who need not have finished onboarding
- a valid request is answered with exactly four topics (title, title_en, subject, reason), the source and has_more
- only the education level and the goal are required; the class, field, language (English) and page (first) have
  defaults
- the choices are the profile's own: an education level, goal or language outside them is refused, with the readable
  message
- an over-long class or field of study, or a page that is negative or not a number, is refused
- the page is passed on, and pages differ
- a failing model is not an error: the answer is the catalogue, marked "fallback"
- each learner has their own limit per minute, and past it the answer is 429 `throttled`
"""

import pytest
from rest_framework.throttling import SimpleRateThrottle

from onboarding.cache import SuggestionCache
from onboarding.catalogue import Catalogue
from onboarding.reasons import ReasonBuilder
from onboarding.router import TopicRouter
from onboarding.service import TopicSuggester
from onboarding.topic_model import TopicModelError
from onboarding.views import TopicSuggestionsView

pytestmark = pytest.mark.django_db

URL = "/api/onboarding/topic-suggestions"
BODY = {"education_level": "school", "grade_or_year": "Class 9", "goal": "exam_prep", "preferred_language": "en"}


@pytest.fixture
def model(monkeypatch):
    """A scripted topic model behind the real service, catalogue and cache."""
    from support.fakes import FakeTopicModel

    fake = FakeTopicModel()
    suggester = TopicSuggester(TopicRouter(Catalogue.default()), ReasonBuilder(), fake, SuggestionCache())
    monkeypatch.setattr(TopicSuggestionsView, "suggester_factory", staticmethod(lambda: suggester))
    return fake


def test_it_needs_a_signed_in_learner(api_client, model):
    assert api_client.post(URL, BODY, format="json").status_code == 401


def test_a_valid_request_gets_four_topics(signed_in_client, model):
    response = signed_in_client.post(URL, BODY, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "catalogue" and body["has_more"] is True
    assert len(body["topics"]) == 4
    assert set(body["topics"][0]) == {"title", "title_en", "subject", "reason"}
    assert body["topics"][0]["reason"] == "Class 9 · often in exams"


def test_a_learner_who_has_not_finished_onboarding_can_ask(signed_in_client, model, user):
    assert user.profile.is_complete is False

    assert signed_in_client.post(URL, BODY, format="json").status_code == 200


def test_only_the_level_and_the_goal_are_required(signed_in_client, model):
    response = signed_in_client.post(URL, {"education_level": "self_learner", "goal": "quick_overview"}, format="json")

    assert response.status_code == 200
    assert response.json()["topics"][0]["reason"] == "Popular with self-learners"
    assert signed_in_client.post(URL, {"goal": "exam_prep"}, format="json").json()["fields"].keys() == {
        "education_level"
    }
    assert signed_in_client.post(URL, {"education_level": "school"}, format="json").json()["fields"].keys() == {"goal"}


@pytest.mark.parametrize(
    "bad",
    [
        {"education_level": "astronaut"},
        {"education_level": ""},
        {"goal": "world_domination"},
        {"preferred_language": "tlh"},
    ],
)
def test_a_choice_outside_the_profiles_is_refused(signed_in_client, model, bad):
    response = signed_in_client.post(URL, {**BODY, **bad}, format="json")

    assert response.status_code == 400
    (field,) = response.json()["fields"]
    assert field == next(iter(bad))


def test_an_unknown_choice_gets_the_readable_message(signed_in_client, model):
    response = signed_in_client.post(URL, {**BODY, "goal": "nope"}, format="json")

    assert response.json()["fields"]["goal"] == ["Please choose one of the options."]


@pytest.mark.parametrize(
    "bad",
    [
        {"grade_or_year": "x" * 101},
        {"field_of_study": "x" * 151},
        {"page": -1},
        {"page": "next"},
        {"page": 10_001},
    ],
)
def test_an_over_long_text_or_a_bad_page_is_refused(signed_in_client, model, bad):
    response = signed_in_client.post(URL, {**BODY, **bad}, format="json")

    assert response.status_code == 400
    assert next(iter(bad)) in response.json()["fields"]


def test_the_page_is_passed_on_and_pages_differ(signed_in_client, model):
    first = signed_in_client.post(URL, BODY, format="json").json()["topics"]
    second = signed_in_client.post(URL, {**BODY, "page": 1}, format="json").json()["topics"]

    assert {t["title_en"] for t in first}.isdisjoint({t["title_en"] for t in second})


def test_a_failing_model_is_not_an_error(signed_in_client, model):
    model.script_suggest(TopicModelError("every model failed"))
    body = {
        "education_level": "undergraduate",
        "field_of_study": "Architecture",
        "goal": "exam_prep",
        "preferred_language": "hi",
    }

    response = signed_in_client.post(URL, body, format="json")

    assert response.status_code == 200
    assert response.json()["source"] == "fallback" and len(response.json()["topics"]) == 4


def test_each_learner_has_their_own_limit(signed_in_client, model, monkeypatch, other_user):
    from rest_framework.test import APIClient

    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "topic_suggestions", "2/min")

    assert signed_in_client.post(URL, BODY, format="json").status_code == 200
    assert signed_in_client.post(URL, BODY, format="json").status_code == 200
    blocked = signed_in_client.post(URL, BODY, format="json")
    assert blocked.status_code == 429 and blocked.json()["code"] == "throttled"

    grace = APIClient()
    grace.post(
        "/api/auth/login", {"email": other_user.email, "password": "correct-horse-battery-staple"}, format="json"
    )
    assert grace.post(URL, BODY, format="json").status_code == 200


def test_the_default_limit_is_thirty_a_minute(settings):
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["topic_suggestions"] == "30/min"

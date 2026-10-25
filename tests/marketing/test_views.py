"""Unit under test: `GET /api/landing/demo-question` (`marketing.views.DemoQuestionView`), the hero card's random
question.

Why: it is called by every visitor of the front page, signed in or not, so it must be open, cheap, never cached by
anything between the server and the browser (or "random" would be the same question for everyone), and limited per
client address. A bank that is empty or a stale browser must not turn into an error page: the page has a built-in
question to fall back on, and relies on a plain 404 for it.

Use cases:
- it needs no sign-in and sends nothing that lets a cache keep the answer
- it returns one active question with everything the card needs: id, subject, level label, band, the question, three
  options, the correct index and both outcomes
- `exclude` keeps a question from coming back; an empty one excludes nothing; a bad one is a 400, not a 500
- questions switched off are never served
- an empty bank is a 404 with the usual error body
- each client address has its own limit (60 a minute by default), and past it the answer is 429 `throttled`
"""

import pytest
from rest_framework.throttling import SimpleRateThrottle

from marketing.models import DemoQuestion

pytestmark = pytest.mark.django_db

URL = "/api/landing/demo-question"


def test_it_needs_no_sign_in_and_cannot_be_cached(api_client):
    response = api_client.get(URL)

    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]


def test_it_returns_one_question_with_everything_the_card_needs(api_client):
    body = api_client.get(URL).json()

    assert set(body) == {
        "id", "subject", "level_label", "band", "question", "options", "correct_index", "outcome_right",
        "outcome_wrong",
    }  # fmt: skip
    assert len(body["options"]) == 3 and 0 <= body["correct_index"] <= 2 and 1 <= body["band"] <= 5
    assert set(body["outcome_right"]) == {"level", "level_label", "lesson_start"}
    assert DemoQuestion.objects.filter(pk=body["id"], is_active=True).exists()


def test_exclude_keeps_a_question_from_coming_back(api_client):
    first = api_client.get(URL).json()["id"]

    assert {api_client.get(URL, {"exclude": first}).json()["id"] for _ in range(25)}.isdisjoint({first})


def test_an_empty_exclude_excludes_nothing(api_client):
    assert api_client.get(URL, {"exclude": ""}).status_code == 200


@pytest.mark.parametrize("bad", ["abc", "1.5", "-3"])
def test_a_bad_exclude_is_a_400(api_client, bad):
    response = api_client.get(URL, {"exclude": bad})

    assert response.status_code == 400
    assert "exclude" in response.json()["fields"]


def test_questions_switched_off_are_never_served(api_client):
    keep = DemoQuestion.objects.first()
    DemoQuestion.objects.exclude(pk=keep.pk).update(is_active=False)
    from django.core.cache import cache

    cache.clear()

    assert {api_client.get(URL).json()["id"] for _ in range(10)} == {keep.pk}


def test_an_empty_bank_is_a_404_with_the_usual_error_body(api_client):
    DemoQuestion.objects.all().delete()

    response = api_client.get(URL)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_each_client_address_has_its_own_limit(api_client, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "landing_demo", "2/min")
    ask = lambda ip: api_client.get(URL, HTTP_X_FORWARDED_FOR=ip)  # noqa: E731

    assert ask("10.0.0.1").status_code == 200
    assert ask("10.0.0.1").status_code == 200
    blocked = ask("10.0.0.1")
    assert blocked.status_code == 429 and blocked.json()["code"] == "throttled"
    assert ask("10.0.0.2").status_code == 200


def test_the_default_limit_is_sixty_a_minute(settings):
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["landing_demo"] == "60/min"

"""Unit under test: `GET /api/public/testimonials` (`marketing.views.PublicTestimonialsView`, `PublicTestimonials`).

Why: it feeds the landing page's "What learners say" for anyone who is not signed in, so it carries the two promises
that page makes: nothing is shown that the learner did not agree to, and nothing invented is ever shown. The rule is
written into the query, not into the DEBUG setting, so a development database full of samples can never leak into a
production page by a mistaken setting. It is called by every visitor, so it is cheap, cached for a moment, and limited
per client address.

Use cases:
- it needs no sign-in, carries only the fields the page shows (no consent flag, no ids of people, no timestamps) and is
  cacheable by the browser for a short time
- only published testimonials with consent and no sample flag are returned, in position order
- a sample is never returned, with DEBUG on or off, even were the database's own constraint missing
- a row published without consent is never returned either (the query checks it as well as the database)
- an empty set is an empty list, not an error
- a change made in the console shows at once (the short cache is cleared by every save and delete)
- a second read within the cache window makes no database query
- each client address has its own limit (60 a minute by default), and past it the answer is 429 `throttled`
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.throttling import SimpleRateThrottle

from marketing.models import Testimonial

pytestmark = pytest.mark.django_db

URL = "/api/public/testimonials"


def real(**fields) -> Testimonial:
    values = dict(
        name="Asha Rao",
        context="Class 12 student",
        quote="It skipped what I knew.",
        is_published=True,
        consent_confirmed=True,
    )
    return Testimonial.objects.create(**{**values, **fields})


def test_it_needs_no_sign_in_and_carries_only_what_the_page_shows(api_client):
    real(rating=5)

    response = api_client.get(URL)

    assert response.status_code == 200
    assert response.json() == {
        "testimonials": [
            {"name": "Asha Rao", "context": "Class 12 student", "quote": "It skipped what I knew.", "rating": 5}
        ]
    }
    assert "max-age=" in response["Cache-Control"] and "public" in response["Cache-Control"]


def test_only_real_published_consented_ones_come_back_in_position_order(api_client):
    real(name="Second", position=2)
    real(name="First", position=1, rating=None)
    real(name="Hidden", is_published=False, consent_confirmed=True)

    names = [t["name"] for t in api_client.get(URL).json()["testimonials"]]

    assert names == ["First", "Second"]


@pytest.fixture
def without_the_constraint():
    """The database refuses to hold a published sample or a published quote without consent. To prove the query does not
    rely on that alone, take the constraint away for one test (DDL is part of the test's transaction, so it is rolled
    back with it)."""
    constraint = next(
        c for c in Testimonial._meta.constraints if c.name == "testimonial_published_needs_consent_and_real"
    )
    with connection.schema_editor() as editor:
        editor.remove_constraint(Testimonial, constraint)


@pytest.mark.parametrize("debug", [True, False])
def test_a_sample_is_never_returned_whatever_debug_is(api_client, settings, debug, without_the_constraint):
    settings.DEBUG = debug
    real(name="Real")
    real(name="[Learner name]", is_sample=True)  # published and consented, which the database would normally refuse

    assert [t["name"] for t in api_client.get(URL).json()["testimonials"]] == ["Real"]


def test_a_row_published_without_consent_is_never_returned(api_client, without_the_constraint):
    real(name="Real")
    real(name="No consent", consent_confirmed=False)

    assert [t["name"] for t in api_client.get(URL).json()["testimonials"]] == ["Real"]


def test_nothing_published_is_an_empty_list(api_client):
    assert api_client.get(URL).json() == {"testimonials": []}


def test_a_change_shows_at_once_despite_the_cache(api_client):
    first = real(name="First")
    assert [t["name"] for t in api_client.get(URL).json()["testimonials"]] == ["First"]

    real(name="Second", position=5)
    assert [t["name"] for t in api_client.get(URL).json()["testimonials"]] == ["First", "Second"]
    first.delete()
    assert [t["name"] for t in api_client.get(URL).json()["testimonials"]] == ["Second"]


def test_a_second_read_makes_no_database_query(api_client):
    real()
    api_client.get(URL)

    with CaptureQueriesContext(connection) as queries:
        api_client.get(URL)

    assert len(queries) == 0


def test_each_client_address_has_its_own_limit(api_client, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "public_pages", "2/min")

    first = [api_client.get(URL, REMOTE_ADDR="10.0.0.1").status_code for _ in range(3)]
    other = api_client.get(URL, REMOTE_ADDR="10.0.0.2").status_code

    assert first == [200, 200, 429] and other == 200
    body = api_client.get(URL, REMOTE_ADDR="10.0.0.1").json()
    assert body["code"] == "throttled"

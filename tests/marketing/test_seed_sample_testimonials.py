"""Unit under test: the `seed_sample_testimonials` management command (`marketing.management.commands`).

Why: a landing page with an empty "What learners say" section is hard to design against, so a developer wants three
placeholder quotes on their own machine. The same command run on a real site would put made-up words next to real
people's, so it refuses to run unless DEBUG is on, and everything it makes is flagged as a sample, unpublished and
without consent: the database refuses to publish such a row and the public endpoint never returns one.

Use cases:
- with DEBUG on it makes three testimonials, each a sample, unpublished, without consent, with a bracketed placeholder
  name such as "[Learner name]" and a bracketed context, in positions after any that exist
- running it again adds nothing (the same three are not made twice)
- with DEBUG off it refuses with an error naming the reason and makes nothing
- what it makes is never on the public endpoint
- it tells the developer how many it made
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from marketing.models import Testimonial

pytestmark = pytest.mark.django_db


def run() -> str:
    out = StringIO()
    call_command("seed_sample_testimonials", stdout=out)
    return out.getvalue()


def test_with_debug_on_it_makes_three_unpublished_samples_with_placeholder_names(settings):
    settings.DEBUG = True

    run()

    rows = list(Testimonial.objects.all())
    assert len(rows) == 3
    assert all(r.is_sample and not r.is_published and not r.consent_confirmed for r in rows)
    assert all(r.name.startswith("[") and r.name.endswith("]") and r.context.startswith("[") for r in rows)
    assert [r.position for r in rows] == sorted({r.position for r in rows}) and len({r.position for r in rows}) == 3
    for row in rows:
        row.full_clean()


def test_they_come_after_the_testimonials_that_already_exist(settings):
    settings.DEBUG = True
    Testimonial.objects.create(name="Real", context="Class 10 student", quote="Good.", position=7)

    run()

    assert min(r.position for r in Testimonial.objects.filter(is_sample=True)) == 8


def test_running_it_again_adds_nothing(settings):
    settings.DEBUG = True

    run()
    again = run()

    assert Testimonial.objects.count() == 3 and "0" in again


def test_with_debug_off_it_refuses_and_makes_nothing(settings):
    settings.DEBUG = False

    with pytest.raises(CommandError, match="DEBUG"):
        run()

    assert not Testimonial.objects.exists()


def test_what_it_makes_is_never_on_the_public_endpoint(settings, api_client):
    settings.DEBUG = True

    run()

    assert api_client.get("/api/public/testimonials").json() == {"testimonials": []}


def test_it_says_how_many_it_made(settings):
    settings.DEBUG = True

    assert "3" in run()

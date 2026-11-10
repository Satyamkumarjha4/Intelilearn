"""Unit under test: `marketing.models.Testimonial`, one quote on the landing page's "What learners say" section.

Why: a testimonial is a real person's words shown to every visitor under their name, so two things must never happen: a
quote shown without the person having agreed to it, and a made-up sample (the ones that exist only to make a developer's
page look full) reaching the public page. The rule is kept twice, in the model's validation (a clear message for the
console) and in a database constraint (so no code path, admin form or script can get round it).

Use cases:
- a complete testimonial is valid, starts unpublished, without consent and not a sample, and prints as its name
- publishing needs the learner's consent: published without consent is refused by the validation and by the database
- a sample can never be published, with consent or without: refused by the validation and by the database
- a consenting, real testimonial can be published, and an unpublished one needs neither
- the rating is optional; when given it is a whole number from 1 to 5, in the validation and in the database
- the quote is at most 300 characters; name, context and quote must not be blank
- testimonials are ordered by position, then by when they were made
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from marketing.models import Testimonial

pytestmark = pytest.mark.django_db


def make(**fields) -> Testimonial:
    values = dict(
        name="Asha Rao", context="Class 12 student", quote="The retake had new questions, so I knew I had learned it."
    )
    return Testimonial(**{**values, **fields})


def test_a_complete_testimonial_is_valid_and_starts_unpublished_and_unconsented():
    testimonial = make()

    testimonial.full_clean()
    testimonial.save()

    assert (testimonial.is_published, testimonial.consent_confirmed, testimonial.is_sample) == (False, False, False)
    assert testimonial.rating is None and str(testimonial) == "Asha Rao"


def test_publishing_without_consent_is_refused_by_the_validation_and_the_database():
    testimonial = make(is_published=True, consent_confirmed=False)

    with pytest.raises(ValidationError) as refused:
        testimonial.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        testimonial.save()

    assert "consent" in refused.value.message_dict["is_published"][0].lower()


@pytest.mark.parametrize("consent", [True, False])
def test_a_sample_can_never_be_published(consent):
    testimonial = make(is_published=True, is_sample=True, consent_confirmed=consent)

    with pytest.raises(ValidationError) as refused:
        testimonial.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        testimonial.save()

    assert "sample" in refused.value.message_dict["is_published"][0].lower()


def test_a_consenting_real_testimonial_can_be_published():
    testimonial = make(is_published=True, consent_confirmed=True)

    testimonial.full_clean()
    testimonial.save()

    assert Testimonial.objects.get().is_published is True


def test_an_unpublished_sample_without_consent_is_fine():
    make(is_sample=True).full_clean()
    make(is_sample=True).save()


@pytest.mark.parametrize("rating", [1, 3, 5, None])
def test_the_rating_is_optional_and_one_to_five(rating):
    make(rating=rating).full_clean()
    make(rating=rating).save()


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_a_rating_outside_one_to_five_is_refused_by_the_validation_and_the_database(rating):
    with pytest.raises(ValidationError) as refused:
        make(rating=rating).full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        make(rating=rating).save()

    assert "rating" in refused.value.message_dict


def test_the_quote_is_at_most_three_hundred_characters():
    make(quote="q" * 300).full_clean()

    with pytest.raises(ValidationError) as refused:
        make(quote="q" * 301).full_clean()

    assert "quote" in refused.value.message_dict


@pytest.mark.parametrize("field", ["name", "context", "quote"])
def test_name_context_and_quote_must_not_be_blank(field):
    with pytest.raises(ValidationError) as refused:
        make(**{field: "   "}).full_clean()

    assert field in refused.value.message_dict


def test_testimonials_are_ordered_by_position_then_age():
    third = Testimonial.objects.create(name="C", context="c", quote="c", position=2)
    first = Testimonial.objects.create(name="A", context="a", quote="a", position=1)
    second = Testimonial.objects.create(name="B", context="b", quote="b", position=1)

    assert list(Testimonial.objects.all()) == [first, second, third]

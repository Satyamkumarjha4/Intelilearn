"""Unit under test: `llm_registry.models.ModelPrice`, a model's price per million tokens for a window of dates, and the
`ModelPrice.objects.in_effect` lookup.

Why: prices change on known dates (the Gemini 3.6 and 3.8 Flash promo ends 2026-12-31), so a price is a row with a
validity window, the page it was read from and the day it was read. Old `ModelCall` rows keep the price they were billed
at because a change is a new row, never an edit. Two rows in force on one day would make the cost ambiguous.

Use cases:
- a price row needs a source page and the day it was read, and an output price that is not below zero
- a window cannot end before it starts
- a long-context price set is all or nothing (threshold, input and output together)
- two windows of one model cannot overlap, but the same dates on two models are fine
- `in_effect` finds the row whose window holds the day, inclusive at both ends, and an open-ended window holds every
  later day
- `in_effect` finds nothing for a day before the first window or for a model with no rows
- the models console reads: the current row and the next one (what the price becomes, and on which day)
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from llm_registry.models import LLMModel, ModelPrice

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def model(gemini):
    return LLMModel.objects.create(provider=gemini, name="gemini-3.6-flash")


def price(model, **kw):
    values = {"input_per_mtok": D("0.75"), "output_per_mtok": D("3.75"), "source_url": "https://example.com/pricing",
              "checked_on": date(2026, 11, 15)}  # fmt: skip
    return ModelPrice(model=model, **{**values, **kw})


def test_a_row_needs_a_source_page_and_the_day_it_was_read(model):
    with pytest.raises(ValidationError) as caught:
        price(model, source_url="", checked_on=None).full_clean()

    assert {"source_url", "checked_on"} <= set(caught.value.message_dict)


def test_a_negative_price_is_refused(model):
    with pytest.raises(ValidationError):
        price(model, output_per_mtok=D("-1")).full_clean()


def test_a_window_cannot_end_before_it_starts(model):
    with pytest.raises(ValidationError) as caught:
        price(model, valid_from=date(2027, 1, 2), valid_until=date(2027, 1, 1)).full_clean()

    assert "valid_until" in caught.value.message_dict


def test_a_long_context_price_set_is_all_or_nothing(model):
    with pytest.raises(ValidationError) as caught:
        price(model, long_context_threshold=200_000, long_input_per_mtok=D("2")).full_clean()

    assert "long_context_threshold" in caught.value.message_dict


def test_two_windows_of_one_model_cannot_overlap(model):
    price(model, valid_until=date(2026, 12, 31)).save()

    with pytest.raises(ValidationError) as caught:
        price(model, valid_from=date(2026, 12, 31)).full_clean()

    assert "valid_from" in caught.value.message_dict


def test_the_same_dates_on_two_models_are_fine(model, gemini):
    other = LLMModel.objects.create(provider=gemini, name="gemini-3.8-flash")
    price(model, valid_until=date(2026, 12, 31)).save()

    price(other, valid_until=date(2026, 12, 31)).full_clean()


def test_in_effect_is_inclusive_at_both_ends_and_an_open_window_holds_every_later_day(model):
    promo = price(model, valid_until=date(2026, 12, 31))
    promo.save()
    later = price(model, input_per_mtok=D("1.5"), output_per_mtok=D("7.5"), valid_from=date(2027, 1, 1))
    later.save()

    found = [ModelPrice.objects.in_effect("gemini", "gemini-3.6-flash", date(*d)) for d in
             [(2026, 6, 1), (2026, 12, 31), (2027, 1, 1), (2030, 1, 1)]]  # fmt: skip

    assert found == [promo, promo, later, later]


def test_in_effect_finds_nothing_before_the_first_window_or_for_a_model_without_rows(model):
    price(model, valid_from=date(2026, 7, 1)).save()

    assert ModelPrice.objects.in_effect("gemini", "gemini-3.6-flash", date(2026, 6, 30)) is None
    assert ModelPrice.objects.in_effect("gemini", "no-such-model", date(2026, 7, 1)) is None


def test_the_next_row_is_what_the_price_becomes(model):
    price(model, valid_until=date(2026, 12, 31)).save()
    later = price(model, input_per_mtok=D("1.5"), output_per_mtok=D("7.5"), valid_from=date(2027, 1, 1))
    later.save()

    assert ModelPrice.objects.next_after("gemini", "gemini-3.6-flash", date(2026, 11, 15)) == later
    assert ModelPrice.objects.next_after("gemini", "gemini-3.6-flash", date(2027, 1, 1)) is None

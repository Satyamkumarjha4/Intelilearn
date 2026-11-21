"""Unit under test: `llm_registry.prices.PriceBook` (every model's price per million tokens, the page it was read from
and the day, with the windows of dates a price applies to), the rows it seeds as `ModelPrice`, and
`manage.py seed_registry --prices`.

Why: with no price a call has no cost, the console's spend figures read $0 and the live suite's cost limit checks
nothing. A price is money arithmetic that people will make pricing decisions on, so each one is kept with the official
page it came from and the day it was read, a promo's end is a date (the Gemini 3.6 and 3.8 Flash price doubles on
2027-01-01), and a price an admin has set is never overwritten.

Use cases:
- every entry names the https page it was read from and the day, has an input and an output price, and has no
  long-context price that is only half given
- the windows of one model never overlap, and a promo's last day and the day after cost differently
- `fill` creates a `ModelPrice` row for each entry whose model is in the registry, says which models the registry has
  that the book does not price, and which entries have no model here
- `fill` is safe to repeat and never changes or duplicates a row that is already there (an admin's figure wins)
- the models of the default registry are all in the book
- `seed_registry --prices` does that to an existing registry and says what it did, without touching bindings or nodes
- loading a profile with `seed_registry` also prices its models
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command

from llm_registry.models import LLMModel, ModelPrice, NodeModelBinding
from llm_registry.prices import PriceBook
from llm_registry.seed import DefaultRegistry

pytestmark = pytest.mark.django_db


class TestTheBook:
    def test_every_entry_says_where_and_when_it_was_read(self):
        for entry in PriceBook.ENTRIES:
            label = f"{entry.provider}/{entry.model}"
            assert entry.source_url.startswith("https://"), label
            assert date.fromisoformat(entry.checked_on), label
            assert entry.input_per_mtok >= 0 and entry.output_per_mtok >= 0, label
            long = [entry.long_context_threshold, entry.long_input_per_mtok, entry.long_output_per_mtok]
            assert all(v is None for v in long) or all(v is not None for v in long), label

    def test_the_windows_of_one_model_do_not_overlap(self):
        by_model: dict[tuple, list] = {}
        for entry in PriceBook.ENTRIES:
            by_model.setdefault((entry.provider, entry.model), []).append(entry)
        for label, entries in by_model.items():
            ordered = sorted(entries, key=lambda e: e.valid_from or date.min)
            for earlier, later in zip(ordered, ordered[1:], strict=False):
                assert earlier.valid_until is not None and earlier.valid_until < later.valid_from, label

    def test_the_flash_promo_ends_on_the_last_day_of_2026(self, gemini):
        LLMModel.objects.create(provider=gemini, name="gemini-3.6-flash")
        PriceBook().fill()

        last_day = ModelPrice.objects.in_effect("gemini", "gemini-3.6-flash", date(2026, 12, 31))
        new_year = ModelPrice.objects.in_effect("gemini", "gemini-3.6-flash", date(2027, 1, 1))

        assert (last_day.input_per_mtok, last_day.output_per_mtok) == (Decimal("0.75"), Decimal("3.75"))
        assert (new_year.input_per_mtok, new_year.output_per_mtok) == (Decimal("1.5"), Decimal("7.5"))

    def test_the_models_of_the_default_registry_are_all_in_the_book(self):
        in_book = {(e.provider, e.model) for e in PriceBook.ENTRIES}

        seeded = {(m["provider"], m["name"]) for m in DefaultRegistry().build()["models"]}

        assert seeded <= in_book, f"No price in the book for: {sorted(seeded - in_book)}"


class TestFill:
    @pytest.fixture
    def registry(self, groq, gemini):
        LLMModel.objects.create(provider=groq, name="openai/gpt-oss-120b")
        LLMModel.objects.create(provider=gemini, name="gemini-3.1-flash-lite")
        LLMModel.objects.create(provider=gemini, name="not-in-the-book")

    def test_it_creates_a_row_for_each_entry_whose_model_is_in_the_registry(self, registry):
        report = PriceBook().fill()

        row = ModelPrice.objects.get(model__name="openai/gpt-oss-120b")
        assert (row.input_per_mtok, row.output_per_mtok, row.cached_input_per_mtok) == (
            Decimal("0.15"), Decimal("0.6"), Decimal("0.075"))  # fmt: skip
        assert row.source_url.startswith("https://") and row.checked_on == date(2026, 11, 15)
        assert sorted(report.filled) == ["gemini/gemini-3.1-flash-lite", "groq/openai/gpt-oss-120b"]
        assert report.unpriced == ["gemini/not-in-the-book"]

    def test_it_is_safe_to_repeat_and_never_changes_a_row_that_is_there(self, registry):
        PriceBook().fill()
        row = ModelPrice.objects.get(model__name="openai/gpt-oss-120b")
        row.input_per_mtok = Decimal("9")
        row.save()

        report = PriceBook().fill()

        assert ModelPrice.objects.filter(model__name="openai/gpt-oss-120b").count() == 1
        assert ModelPrice.objects.get(model__name="openai/gpt-oss-120b").input_per_mtok == Decimal("9")
        assert report.filled == []

    def test_a_window_an_admin_already_covers_is_left_alone(self, registry):
        model = LLMModel.objects.get(name="gemini-3.1-flash-lite")
        ModelPrice.objects.create(model=model, input_per_mtok=1, output_per_mtok=2, source_url="https://x.test/p",
                                  checked_on=date(2026, 11, 1))  # fmt: skip

        PriceBook().fill()

        assert ModelPrice.objects.filter(model=model).count() == 1


class TestSeedRegistryPrices:
    def test_prices_fills_an_existing_registry_without_touching_bindings(self, registry_in_place, capsys):
        before = NodeModelBinding.objects.count()

        call_command("seed_registry", "--prices")

        assert ModelPrice.objects.exists()
        assert NodeModelBinding.objects.count() == before
        assert "Priced" in capsys.readouterr().out

    def test_loading_a_profile_also_prices_its_models(self, db):
        call_command("seed_registry")

        assert ModelPrice.objects.filter(model__name="openai/gpt-oss-120b").exists()
        assert not LLMModel.objects.filter(prices__isnull=True, provider__key="groq").exists()

    @pytest.fixture
    def registry_in_place(self, db):
        call_command("seed_registry")
        ModelPrice.objects.all().delete()

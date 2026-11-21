"""Unit under test: `llm_registry.prices.PriceBook` (each model's price per million tokens, with where it was read and
when), the prices the default registry seeds, and `manage.py seed_registry --prices`.

Why: `ModelCall.cost` is only filled when the model has a price, so with no prices the console's spend figures read $0,
the monthly budget never fills and the live suite's cost limit checked nothing. A price is money arithmetic that people
will make pricing decisions on, so each one is kept with the official page it came from and the day it was read, and a
model whose price could not be confirmed on an official page is left empty (and listed) instead of guessed.

Use cases:
- every entry names the https page it was read from and the date; a priced entry has both an input and an output price,
  and an entry without a price says why
- the default registry seeds each model with the book's prices, and no model without a confirmed price gets one
- `fill_missing` sets the prices of models that have none, leaves a model that already has a price alone (an admin's
  figure wins), and reports the models it filled, the ones the book has no price for, and the ones it does not know
- `seed_registry --prices` does that to an existing registry and says what it did, without touching bindings or nodes
- a priced model's calls are costed (input and output tokens at their own prices) and an unpriced model's are not
"""

from decimal import Decimal

import pytest
from django.core.management import call_command

from llm_registry.models import LLMModel, NodeModelBinding
from llm_registry.prices import ModelPrice, PriceBook
from llm_registry.recorder import ModelCallRecorder
from llm_registry.seed import DefaultRegistry

pytestmark = pytest.mark.django_db


class TestTheBook:
    def test_every_entry_says_where_and_when_it_was_read_and_why_it_has_no_price(self):
        for entry in PriceBook.ENTRIES:
            assert entry.source_url.startswith("https://"), entry.model
            assert len(entry.checked_on) == 10 and entry.checked_on[4] == "-", entry.model  # 2026-11-15
            if entry.input_per_mtok is None and entry.output_per_mtok is None:
                assert len(entry.note) > 20, f"{entry.model} has no price and no reason"
            else:
                assert entry.input_per_mtok is not None and entry.output_per_mtok is not None, entry.model

    def test_a_price_is_found_by_provider_and_model(self):
        entry = PriceBook().entry("groq", "openai/gpt-oss-120b")

        assert (entry.input_per_mtok, entry.output_per_mtok) == (Decimal("0.15"), Decimal("0.60"))
        assert PriceBook().entry("groq", "no-such-model") is None

    def test_the_models_of_the_default_registry_are_all_in_the_book(self):
        in_book = {(e.provider, e.model) for e in PriceBook.ENTRIES}

        assert {(m["provider"], m["name"]) for m in DefaultRegistry().build()["models"]} <= in_book


class TestTheSeed:
    def test_the_default_registry_carries_the_books_prices_and_no_invented_ones(self):
        for model in DefaultRegistry().build()["models"]:
            entry = PriceBook().entry(model["provider"], model["name"])
            assert model["input_cost_per_mtok"] == (
                None if entry.input_per_mtok is None else str(entry.input_per_mtok)
            ), model["name"]
            assert model["output_cost_per_mtok"] == (
                None if entry.output_per_mtok is None else str(entry.output_per_mtok)
            ), model["name"]

    def test_loading_the_seed_stores_the_prices(self):
        call_command("seed_registry")

        priced = LLMModel.objects.get(provider__key="groq", name="openai/gpt-oss-20b")
        assert (priced.input_cost_per_mtok, priced.output_cost_per_mtok) == (Decimal("0.0750"), Decimal("0.3000"))


class TestFillMissing:
    @pytest.fixture
    def models(self, groq, gemini):
        def make(provider, name, **prices):
            return LLMModel.objects.create(provider=provider, name=name, **prices)

        return make

    def test_a_model_with_no_price_gets_the_books(self, models, groq):
        model = models(groq, "openai/gpt-oss-120b")

        report = PriceBook().fill_missing()

        model.refresh_from_db()
        assert (model.input_cost_per_mtok, model.output_cost_per_mtok) == (Decimal("0.1500"), Decimal("0.6000"))
        assert report.filled == ["groq/openai/gpt-oss-120b"]

    def test_a_model_that_already_has_a_price_keeps_it(self, models, groq):
        model = models(groq, "openai/gpt-oss-120b", input_cost_per_mtok=Decimal("9"), output_cost_per_mtok=None)

        report = PriceBook().fill_missing()

        model.refresh_from_db()
        assert model.input_cost_per_mtok == Decimal("9.0000") and model.output_cost_per_mtok is None
        assert report.filled == []

    def test_models_without_a_confirmed_price_and_unknown_models_are_reported_not_priced(
        self, models, groq, monkeypatch
    ):
        listed_entry = ModelPrice(
            "groq", "listed-without-price", None, None, "https://x.example", "2026-11-15", "No price is published."
        )
        monkeypatch.setattr(PriceBook, "ENTRIES", (listed_entry,))
        listed, unknown = models(groq, "listed-without-price"), models(groq, "never-heard-of-it")

        report = PriceBook().fill_missing()

        for model in (listed, unknown):
            model.refresh_from_db()
            assert model.input_cost_per_mtok is None and model.output_cost_per_mtok is None
        assert report.unpriced == ["groq/listed-without-price"] and report.unknown == ["groq/never-heard-of-it"]


class TestTheCommand:
    def test_it_prices_an_existing_registry_and_leaves_bindings_and_nodes_alone(self, capsys):
        call_command("seed_registry")
        LLMModel.objects.update(input_cost_per_mtok=None, output_cost_per_mtok=None)
        bindings = list(NodeModelBinding.objects.values_list("pk", "priority"))

        call_command("seed_registry", "--prices")

        out = capsys.readouterr().out
        assert LLMModel.objects.filter(input_cost_per_mtok__isnull=False).exists()
        assert list(NodeModelBinding.objects.values_list("pk", "priority")) == bindings
        assert "Priced" in out and "groq/openai/gpt-oss-120b" in out

    def test_it_lists_the_models_that_still_have_no_price(self, capsys):
        call_command("seed_registry")
        LLMModel.objects.update(input_cost_per_mtok=None, output_cost_per_mtok=None)

        call_command("seed_registry", "--prices")

        assert "No confirmed price" in capsys.readouterr().out


class TestCostFollowsThePrice:
    def test_input_and_output_tokens_are_costed_at_their_own_prices(self, resolved_model):
        model = resolved_model("m", input_cost_per_mtok=0.15, output_cost_per_mtok=0.60)

        assert ModelCallRecorder.cost(model, 1_000_000, 1_000_000) == pytest.approx(0.75)

    def test_a_model_without_a_price_has_no_cost(self, resolved_model):
        assert ModelCallRecorder.cost(resolved_model("m"), 1_000, 1_000) is None

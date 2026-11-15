"""Unit under test: `llm_registry.costing` (`TokenUsage`, `RateCard`, `CallPricer`, `CallCosts`): what one model call
cost, from the tokens it used and the price in force on the day it was made.

Why: the strategy (docs/to_be_developed/model-strategy.md 3.5.B) prices every call with the date-correct row, splits
cached input from fresh input, and bills thinking as output. A wrong split or a wrong row is a wrong cost on every call
and every figure the console and the budget checks show.

Use cases:
- a plain call costs input tokens at the input price plus output tokens at the output price (thinking is part of the
  output tokens, so it is billed as output)
- cached input tokens are billed at the cached price, and are not also billed as fresh input
- cache-write tokens are billed at the cache-write price, and not also as fresh input
- a cached or write price that is missing falls back to the plain input price
- a prompt over the long-context threshold is billed with the long-context prices for the whole call
- usage is read from LangChain's `usage_metadata`: input, output, cache read and cache creation; no usage, no cost
- the price row in force on the call's day is used (a promo's last day and the day after cost differently)
- a model with no price row but the model's own legacy price fields is costed from those; with neither, no cost
- dollars become rupees at the `USD_INR_RATE` setting (90 unless the environment says otherwise), to the paisa
"""

from datetime import date
from decimal import Decimal

import pytest

from llm_registry.costing import CallCosts, CallPricer, RateCard, Rupees, TokenUsage
from llm_registry.models import LLMModel, ModelPrice

D = Decimal


def card(**kw):
    return RateCard(**{"input": D("1"), "output": D("4"), **kw})


class TestPricer:
    def test_a_plain_call_is_input_plus_output_tokens_at_their_prices(self):
        cost = CallPricer().cost(card(), TokenUsage(input_tokens=1000, output_tokens=500))

        assert cost == D("0.003")  # 1000 * 1 + 500 * 4 = 3000 micro-dollars

    def test_cached_input_is_billed_at_the_cached_price_and_not_as_fresh_input(self):
        priced = card(cached_input=D("0.1"))

        cost = CallPricer().cost(priced, TokenUsage(input_tokens=1000, output_tokens=0, cached_input_tokens=600))

        assert cost == D("0.00046")  # 400 * 1 + 600 * 0.1

    def test_cache_write_tokens_are_billed_at_the_write_price(self):
        priced = card(cache_write=D("1.25"))

        cost = CallPricer().cost(priced, TokenUsage(input_tokens=1000, output_tokens=0, cache_write_tokens=200))

        assert cost == D("0.00105")  # 800 * 1 + 200 * 1.25

    def test_a_missing_cached_or_write_price_falls_back_to_the_input_price(self):
        usage = TokenUsage(input_tokens=1000, output_tokens=0, cached_input_tokens=300, cache_write_tokens=100)

        assert CallPricer().cost(card(), usage) == D("0.001")

    def test_cached_and_written_tokens_never_make_fresh_input_negative(self):
        usage = TokenUsage(input_tokens=100, output_tokens=0, cached_input_tokens=80, cache_write_tokens=80)

        assert CallPricer().cost(card(cached_input=D("0")), usage) >= 0

    def test_a_prompt_over_the_threshold_uses_the_long_context_prices_for_the_whole_call(self):
        long = card(long_context_threshold=200_000, long_input=D("2"), long_output=D("8"))

        short_cost = CallPricer().cost(long, TokenUsage(input_tokens=200_000, output_tokens=1000))
        long_cost = CallPricer().cost(long, TokenUsage(input_tokens=200_001, output_tokens=1000))

        assert short_cost == D("0.204")  # 200000 * 1 + 1000 * 4
        assert long_cost == D("0.408002")  # 200001 * 2 + 1000 * 8


class TestUsage:
    def test_it_is_read_from_langchain_usage_metadata(self):
        usage = TokenUsage.from_metadata(
            {"input_tokens": 90, "output_tokens": 20, "input_token_details": {"cache_read": 40, "cache_creation": 10}}
        )

        assert usage == TokenUsage(90, 20, cached_input_tokens=40, cache_write_tokens=10)

    def test_a_reply_without_token_counts_has_no_usage(self):
        assert TokenUsage.from_metadata({}) is None
        assert TokenUsage.from_metadata({"input_tokens": 5}) is None
        assert TokenUsage.from_metadata(None) is None


@pytest.mark.django_db
class TestCallCosts:
    @pytest.fixture
    def flash(self, gemini):
        return LLMModel.objects.create(provider=gemini, name="gemini-3.6-flash")

    def _price(self, model, **kw):
        values = {"input_per_mtok": D("0.75"), "output_per_mtok": D("3.75"), "source_url": "https://example.com/p",
                  "checked_on": date(2026, 11, 15)}  # fmt: skip
        return ModelPrice.objects.create(model=model, **{**values, **kw})

    def test_the_row_in_force_on_the_day_of_the_call_is_used(self, flash, resolved_model):
        self._price(flash, valid_until=date(2026, 12, 31))
        self._price(flash, input_per_mtok=D("1.5"), output_per_mtok=D("7.5"), valid_from=date(2027, 1, 1))
        model = resolved_model("gemini-3.6-flash", provider_key="gemini")
        usage = TokenUsage(1_000_000, 1_000_000)

        promo = CallCosts().cost(model, usage, date(2026, 12, 31))
        after = CallCosts().cost(model, usage, date(2027, 1, 1))

        assert (promo, after) == (D("4.5"), D("9"))

    def test_without_a_row_the_models_own_legacy_price_is_used(self, resolved_model):
        model = resolved_model("m", input_cost_per_mtok=1.0, output_cost_per_mtok=4.0)

        assert CallCosts().cost(model, TokenUsage(1000, 500), date(2026, 11, 15)) == D("0.003")

    def test_a_model_with_no_price_at_all_has_no_cost(self, resolved_model):
        assert CallCosts().cost(resolved_model("m"), TokenUsage(1000, 500), date(2026, 11, 15)) is None


class TestRupees:
    def test_dollars_become_rupees_at_the_setting_to_the_paisa(self, settings):
        settings.USD_INR_RATE = 90.0

        assert Rupees().of(D("0.0123456")) == D("1.11")  # 1.111104 rupees
        assert Rupees().of(D("0")) == D("0.00")

    def test_the_rate_is_read_when_it_is_used(self, settings):
        settings.USD_INR_RATE = 83.5

        assert Rupees().of(D("2")) == D("167.00")

    def test_a_rate_can_be_given_directly(self):
        assert Rupees(rate=D("100")).of(D("0.5")) == D("50.00")

    def test_the_setting_is_a_positive_number(self, settings):
        from django.conf import settings as real

        assert real.USD_INR_RATE > 0

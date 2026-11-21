"""What one model call cost: the tokens it used, priced with the row in force on the day it was made.

`TokenUsage` is what a reply reports, `RateCard` one set of prices (US dollars per million tokens), `CallPricer` the
arithmetic, `CallCosts` the lookup of the card for a model and a day. Thinking tokens are part of the output tokens at
every provider, so they are billed as output; cached input and cache writes have their own prices and are never also
billed as fresh input.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from .resolver import ResolvedModel

ONE_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0

    @classmethod
    def from_metadata(cls, usage: dict | None) -> "TokenUsage | None":
        """From LangChain's `usage_metadata`; None when the reply did not say how many tokens it used."""
        usage = usage or {}
        if usage.get("input_tokens") is None or usage.get("output_tokens") is None:
            return None
        details = usage.get("input_token_details") or {}
        return cls(
            usage["input_tokens"],
            usage["output_tokens"],
            cached_input_tokens=details.get("cache_read") or 0,
            cache_write_tokens=details.get("cache_creation") or 0,
        )


@dataclass(frozen=True)
class RateCard:
    """Prices in US dollars per million tokens. A missing cached or write price means the plain input price."""

    input: Decimal
    output: Decimal
    cached_input: Decimal | None = None
    cache_write: Decimal | None = None
    long_context_threshold: int | None = None
    long_input: Decimal | None = None
    long_output: Decimal | None = None
    long_cached_input: Decimal | None = None

    @classmethod
    def of_row(cls, row) -> "RateCard":
        """From a `ModelPrice`."""
        return cls(
            row.input_per_mtok,
            row.output_per_mtok,
            row.cached_input_per_mtok,
            row.cache_write_per_mtok,
            row.long_context_threshold,
            row.long_input_per_mtok,
            row.long_output_per_mtok,
            row.long_cached_input_per_mtok,
        )

    @classmethod
    def legacy(cls, model: ResolvedModel) -> "RateCard | None":
        """From the two prices typed on the model itself (used only when it has no price rows)."""
        if model.input_cost_per_mtok is None:
            return None
        return cls(Decimal(str(model.input_cost_per_mtok)), Decimal(str(model.output_cost_per_mtok or 0)))

    def for_prompt(self, input_tokens: int) -> "RateCard":
        """The prices for a prompt of this size: the long-context ones past the threshold, for the whole call."""
        if self.long_context_threshold is None or input_tokens <= self.long_context_threshold:
            return self
        return RateCard(
            input=self.long_input,
            output=self.long_output,
            cached_input=self.long_cached_input if self.long_cached_input is not None else self.cached_input,
            cache_write=self.cache_write,
        )


class CallPricer:
    def cost(self, card: RateCard, usage: TokenUsage) -> Decimal:
        card = card.for_prompt(usage.input_tokens)
        cached_price = card.cached_input if card.cached_input is not None else card.input
        write_price = card.cache_write if card.cache_write is not None else card.input
        fresh = max(usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens, 0)
        micro = (
            fresh * card.input
            + usage.cached_input_tokens * cached_price
            + usage.cache_write_tokens * write_price
            + usage.output_tokens * card.output
        )
        return micro / ONE_MILLION


class PriceLookup(Protocol):
    def card(self, provider_key: str, model_name: str, day: date) -> RateCard | None: ...


class PriceRows:
    """The prices kept in the database: the `ModelPrice` row whose window holds the day."""

    def card(self, provider_key: str, model_name: str, day: date) -> RateCard | None:
        from .models import ModelPrice  # the models import the profiles, which import this package's settings

        row = ModelPrice.objects.in_effect(provider_key, model_name, day)
        return RateCard.of_row(row) if row else None


class CallCosts:
    """The cost of a call: the price row in force that day, else the model's own legacy price, else nothing."""

    def __init__(self, prices: PriceLookup | None = None, pricer: CallPricer | None = None):
        self._prices = prices if prices is not None else PriceRows()
        self._pricer = pricer if pricer is not None else CallPricer()

    def cost(self, model: ResolvedModel, usage: TokenUsage | None, day: date) -> Decimal | None:
        if usage is None:
            return None
        card = self._prices.card(model.provider_key, model.model_name, day) or RateCard.legacy(model)
        return self._pricer.cost(card, usage) if card else None


class Rupees:
    """Dollars as rupees at the `USD_INR_RATE` setting (read each time, so a change needs no restart of a test)."""

    PAISA = Decimal("0.01")

    def __init__(self, rate: Decimal | None = None):
        self._rate = rate

    def of(self, dollars: Decimal) -> Decimal:
        from django.conf import settings

        rate = self._rate if self._rate is not None else Decimal(str(settings.USD_INR_RATE))
        return (Decimal(dollars) * rate).quantize(self.PAISA, rounding=ROUND_HALF_UP)

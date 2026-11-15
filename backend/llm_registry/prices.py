"""What each model costs per million tokens (US dollars), where the figure was read and when.

`ModelCall.cost` is `input_tokens × input price + output_tokens × output price`, and only exists when the model has a
price. A price here was read from the provider's own pricing page; a model whose price could not be confirmed on an
official page has none (an entry with `None` prices and a note saying why) and is listed by
`manage.py seed_registry --prices` instead of being guessed. To confirm one: read the page, put the figures and the
date here, then run `seed_registry --prices` (it fills models that have no price and never overwrites one that has).

Output tokens include the model's thinking tokens (both providers bill them as output).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import ClassVar

GEMINI_PRICING = "https://ai.google.dev/gemini-api/docs/pricing"
GROQ_MODELS = "https://console.groq.com/docs/models"

_GEMINI_UNCONFIRMED = (
    "Not confirmed: that page now redirects to aistudio.google.com/docs/pricing, which could not be read when this "
    "was checked, so no figure is used. Read the page and fill it in."
)


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    model: str
    input_per_mtok: Decimal | None
    output_per_mtok: Decimal | None
    source_url: str
    checked_on: str  # the day the page was read, ISO
    note: str = ""

    @classmethod
    def priced(cls, provider: str, model: str, source: str, day: str, price_in: str, price_out: str) -> "ModelPrice":
        return cls(provider, model, Decimal(price_in), Decimal(price_out), source, day)


@dataclass(frozen=True)
class FillReport:
    filled: list[str] = field(default_factory=list)  # priced now
    unpriced: list[str] = field(default_factory=list)  # in the book, but without a confirmed price
    unknown: list[str] = field(default_factory=list)  # not in the book at all


class PriceBook:
    ENTRIES: ClassVar[tuple[ModelPrice, ...]] = (
        # Groq: the model table on its models page, "PRICE PER 1M TOKENS" (printed with "$"), on-demand, 2026-11-15.
        ModelPrice.priced("groq", "openai/gpt-oss-120b", GROQ_MODELS, "2026-11-15", "0.15", "0.60"),
        ModelPrice.priced("groq", "openai/gpt-oss-20b", GROQ_MODELS, "2026-11-15", "0.075", "0.30"),
        ModelPrice(
            "groq",
            "llama-3.3-70b-versatile",
            None,
            None,
            GROQ_MODELS,
            "2026-11-15",
            "The page prints ContactSales for both prices (an enterprise model): no on-demand price is published.",
        ),
        *(
            ModelPrice("gemini", name, None, None, GEMINI_PRICING, "2026-11-15", _GEMINI_UNCONFIRMED)
            for name in (
                "gemini-3.5-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite",
                "gemini-2.5-pro",
            )
        ),
    )

    def entry(self, provider: str, model: str) -> ModelPrice | None:
        return next((e for e in self.ENTRIES if (e.provider, e.model) == (provider, model)), None)

    def fill_missing(self) -> FillReport:
        """Price the models that have no price at all. A model with any price already set (an admin's figure) is left
        alone."""
        from .models import LLMModel

        filled, unpriced, unknown = [], [], []
        rows = LLMModel.objects.select_related("provider").filter(
            input_cost_per_mtok__isnull=True, output_cost_per_mtok__isnull=True
        )
        for row in rows.order_by("provider__key", "name"):
            label = f"{row.provider.key}/{row.name}"
            entry = self.entry(row.provider.key, row.name)
            if entry is None:
                unknown.append(label)
            elif entry.input_per_mtok is None or entry.output_per_mtok is None:
                unpriced.append(label)
            else:
                row.input_cost_per_mtok, row.output_cost_per_mtok = entry.input_per_mtok, entry.output_per_mtok
                row.save(update_fields=["input_cost_per_mtok", "output_cost_per_mtok"])
                filled.append(label)
        return FillReport(filled, unpriced, unknown)

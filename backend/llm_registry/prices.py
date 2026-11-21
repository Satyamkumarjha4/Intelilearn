"""What each model costs per million tokens (US dollars), the page it was read from, the day it was read, and the dates
it applies to.

The book is the seed of the `ModelPrice` table: `PriceBook().fill()` creates a row for every entry whose model is in
the registry and never changes a row that is already there (an admin's figure wins). Every figure was read from the
provider's own pricing page, on the day written beside it; a price that has an end date (a promo) is two entries, the
promo and what follows it, so the cost of a call is the price of the day it was made. Output includes thinking tokens:
every provider bills them as output.

A model with no entry is listed by `fill` and has no cost until someone reads its page and adds it here. Never guess.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import ClassVar

GEMINI_PRICING = "https://aistudio.google.com/docs/pricing"
GROQ_MODELS = "https://console.groq.com/docs/models"
OPENAI_PRICING = "https://developers.openai.com/api/docs/pricing"
ANTHROPIC_PRICING = "https://platform.claude.com/docs/en/about-claude/pricing"
READ_ON = "2026-11-15"
PROMO_END, AFTER_PROMO = date(2026, 12, 31), date(2027, 1, 1)


@dataclass(frozen=True)
class PriceEntry:
    provider: str
    model: str
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    source_url: str
    checked_on: str  # the day the page was read, ISO
    cached_input_per_mtok: Decimal | None = None
    cache_write_per_mtok: Decimal | None = None
    long_context_threshold: int | None = None
    long_input_per_mtok: Decimal | None = None
    long_output_per_mtok: Decimal | None = None
    long_cached_input_per_mtok: Decimal | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    note: str = ""

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


def entry(
    provider: str,
    model: str,
    source: str,
    price_in: str,
    price_out: str,
    cached: str | None = None,
    *,
    write: str | None = None,
    long: tuple[int, str, str, str | None] | None = None,
    **window,
) -> PriceEntry:
    """One priced model, prices written as text so no float ever touches them. `long` is the long-context set: the
    threshold in tokens, then input, output and cached input; `window` is `valid_from` and `valid_until`."""
    dec = lambda v: None if v is None else Decimal(v)  # noqa: E731
    threshold, long_in, long_out, long_cached = long or (None, None, None, None)
    return PriceEntry(
        provider, model, Decimal(price_in), Decimal(price_out), source, READ_ON, dec(cached), dec(write),
        threshold, dec(long_in), dec(long_out), dec(long_cached), **window,
    )  # fmt: skip


def flash(model: str) -> tuple[PriceEntry, PriceEntry]:
    """Gemini 3.6 and 3.8 Flash: a promo price to the end of 2026, double from 2027-01-01."""
    promo = entry("gemini", model, GEMINI_PRICING, "0.75", "3.75", "0.075", valid_until=PROMO_END,
                  note="Promotional price, shown with its end date on the pricing page.")  # fmt: skip
    after = entry("gemini", model, GEMINI_PRICING, "1.50", "7.50", "0.15", valid_from=AFTER_PROMO)
    return promo, after


@dataclass
class FillReport:
    filled: list[str] = field(default_factory=list)  # a row was created
    unchanged: list[str] = field(default_factory=list)  # the model already has a price for those dates
    unpriced: list[str] = field(default_factory=list)  # a model in the registry that the book has no entry for


class PriceBook:
    ENTRIES: ClassVar[tuple[PriceEntry, ...]] = (
        # Groq: "PRICE PER 1M TOKENS" on the models page; cached input is "50% off" the prompt-caching page.
        entry("groq", "openai/gpt-oss-120b", GROQ_MODELS, "0.15", "0.60", "0.075"),
        entry("groq", "openai/gpt-oss-20b", GROQ_MODELS, "0.075", "0.30", "0.0375"),
        # Gemini: the Standard tab of the pricing page, paid tier; output includes thinking tokens.
        entry("gemini", "gemini-3.1-flash-lite", GEMINI_PRICING, "0.25", "1.50", "0.025"),
        entry("gemini", "gemini-3.5-flash-lite", GEMINI_PRICING, "0.30", "2.50", "0.03"),
        *flash("gemini-3.6-flash"),
        *flash("gemini-3.8-flash"),
        entry("gemini", "gemini-4-hydrogen", GEMINI_PRICING, "1.50", "7.50", "0.075"),
        # OpenAI: short context is up to 272K input tokens, long context above.
        entry("openai", "gpt-6-luna", OPENAI_PRICING, "0.10", "0.50", "0.01", long=(272_000, "0.20", "0.75", "0.02")),
        entry(
            "openai", "gpt-6.1-terra", OPENAI_PRICING, "1.00", "5.00", "0.05", long=(272_000, "2.00", "7.50", "0.10")
        ),  # fmt: skip
        # Anthropic: Haiku 5.5 is cheaper up to a 100K-token prompt; the 5-minute cache write is 1.25 times the input.
        entry(
            "anthropic",
            "claude-haiku-5-5",
            ANTHROPIC_PRICING,
            "0.10",
            "0.50",
            "0.01",
            write="0.125",
            long=(100_000, "0.50", "2.50", "0.05"),
        ),  # fmt: skip
        entry("anthropic", "claude-sonnet-5-5", ANTHROPIC_PRICING, "2.00", "10.00", "0.10", write="2.50"),
    )

    def entries_of(self, provider: str, model: str) -> list[PriceEntry]:
        return [e for e in self.ENTRIES if (e.provider, e.model) == (provider, model)]

    def fill(self) -> FillReport:
        """A `ModelPrice` row for every entry whose model is in the registry. A row an admin has set for the same dates
        is left alone, and a model the book has no entry for is reported, not guessed."""
        from django.core.exceptions import ValidationError

        from .models import LLMModel, ModelPrice

        report = FillReport()
        for model in LLMModel.objects.select_related("provider").order_by("provider__key", "name"):
            label = f"{model.provider.key}/{model.name}"
            entries = self.entries_of(model.provider.key, model.name)
            if not entries:
                report.unpriced.append(label)
                continue
            created = False
            for e in entries:
                row = ModelPrice(
                    model=model, input_per_mtok=e.input_per_mtok, output_per_mtok=e.output_per_mtok,
                    cached_input_per_mtok=e.cached_input_per_mtok, cache_write_per_mtok=e.cache_write_per_mtok,
                    long_context_threshold=e.long_context_threshold, long_input_per_mtok=e.long_input_per_mtok,
                    long_output_per_mtok=e.long_output_per_mtok,
                    long_cached_input_per_mtok=e.long_cached_input_per_mtok, valid_from=e.valid_from,
                    valid_until=e.valid_until, source_url=e.source_url, checked_on=date.fromisoformat(e.checked_on),
                    note=e.note,
                )  # fmt: skip
                try:
                    row.full_clean()
                except ValidationError:  # the model already has a price for those dates
                    continue
                row.save()
                created = True
            (report.filled if created else report.unchanged).append(label)
        return report

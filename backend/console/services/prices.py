"""A model's price as the console shows it: what applies today, what it becomes and when, and what to look at.

Read from the model's own `ModelPrice` rows (prefetched by the list, so the page makes no query per model), or, for a
model with none, the price typed on the model itself, marked legacy. The warnings are the ones a person would want
before a lesson's cost changes under them: no price, a price that ends or changes soon, a model the provider is about to
stop serving, a deprecated one.
"""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from llm_registry.models import LLMModel, ModelPrice


class ModelPrices:
    #: how far ahead a change of price or a shutdown is worth a warning
    WARN_DAYS = 60

    def __init__(self, today: Callable[[], date] | None = None):
        self._today = today or (lambda: timezone.now().date())

    def current(self, model: LLMModel) -> dict | None:
        row = self._in_effect(model)
        if row:
            return {
                "input": self._text(row.input_per_mtok),
                "output": self._text(row.output_per_mtok),
                "cached_input": self._text(row.cached_input_per_mtok),
                "legacy": False,
                "checked_on": row.checked_on.isoformat(),
                "source_url": row.source_url,
                "valid_until": row.valid_until.isoformat() if row.valid_until else None,
            }
        if model.input_cost_per_mtok is not None:
            return {
                "input": self._text(model.input_cost_per_mtok),
                "output": self._text(model.output_cost_per_mtok or Decimal(0)),
                "cached_input": None,
                "legacy": True,
                "checked_on": None,
                "source_url": "",
                "valid_until": None,
            }
        return None

    def upcoming(self, model: LLMModel) -> dict | None:
        row = self._next(model)
        if row is None:
            return None
        return {
            "from": row.valid_from.isoformat(),
            "input": self._text(row.input_per_mtok),
            "output": self._text(row.output_per_mtok),
        }

    def warnings(self, model: LLMModel) -> list[str]:
        today, horizon = self._today(), self._today() + timedelta(days=self.WARN_DAYS)
        found = []
        row = self._in_effect(model)
        if row is None and model.input_cost_per_mtok is None:
            found.append("No price: its calls have no cost.")
        elif row is not None and row.valid_until is not None and row.valid_until <= horizon:
            following = self._next(model)
            if following:
                found.append(
                    f"The price changes on {following.valid_from.isoformat()}: "
                    f"{self._dollars(row)} becomes {self._dollars(following)}."
                )
            else:
                found.append(f"Its price ends on {row.valid_until.isoformat()} and no later price is set.")
        if model.shutdown_on is not None and model.shutdown_on <= horizon:
            verb = "stops serving it on" if model.shutdown_on >= today else "stopped serving it on"
            found.append(f"The provider {verb} {model.shutdown_on.isoformat()}.")
        if model.status == "deprecated":
            found.append("Deprecated by its provider.")
        return found

    def _rows(self, model: LLMModel) -> list[ModelPrice]:
        return sorted(model.prices.all(), key=lambda row: row.valid_from or date.min)

    def _in_effect(self, model: LLMModel) -> ModelPrice | None:
        today = self._today()
        for row in self._rows(model):
            started = row.valid_from is None or row.valid_from <= today
            not_ended = row.valid_until is None or today <= row.valid_until
            if started and not_ended:
                return row
        return None

    def _next(self, model: LLMModel) -> ModelPrice | None:
        today = self._today()
        return next((row for row in self._rows(model) if row.valid_from is not None and row.valid_from > today), None)

    @staticmethod
    def _text(value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")

    @staticmethod
    def _dollars(row: ModelPrice) -> str:
        def plain(value: Decimal) -> str:
            text = format(value.normalize(), "f")
            if "." not in text:
                text += "."
            return text + "0" * max(0, 2 - len(text.partition(".")[2]))

        return f"${plain(row.input_per_mtok)} / ${plain(row.output_per_mtok)}"

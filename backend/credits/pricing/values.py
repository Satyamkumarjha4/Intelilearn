"""What a quote is made of: lines of the price table, and their total."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceLine:
    key: str  # the row of the price table
    label: str  # in the learner's words
    credits: int


@dataclass(frozen=True)
class PriceQuote:
    lines: tuple[PriceLine, ...] = ()

    @property
    def total(self) -> int:
        return sum(line.credits for line in self.lines)

    def as_json(self) -> list[dict]:
        """The lines as they are kept on a reserve and sent to a screen."""
        return [{"key": line.key, "label": line.label, "credits": line.credits} for line in self.lines]

"""One question, one answer: what does this action cost? Used by the gate (which then charges) and the quote endpoint
(which only tells), so they cannot disagree."""

from .book import PriceBook
from .rules import PriceRules
from .values import PriceQuote


class PriceQuoter:
    def __init__(self, book: PriceBook | None = None):
        self.book = book or PriceBook()

    def quote(self, action, size) -> PriceQuote:
        """The lines and total of `action` asked with `size`. `UnknownHints` for a hint the rule cannot read,
        `PriceUnavailable` for a price the table lacks, `KeyError` for an action with no rule."""
        return PriceRules.for_action(action, self.book).quote(size)

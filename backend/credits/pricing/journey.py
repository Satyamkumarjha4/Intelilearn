"""What a screen that starts a staged piece of work shows (plan §5.5): the part due now, the part that follows, and one
total. A new lesson from a Quick check is paid in two stages (the Quick check now, the rest after it); everything
else is
paid in one. No journey has a range."""

from dataclasses import dataclass

from lessons.metering import MeteredAction

from .quoter import PriceQuoter
from .rules import LessonCreatePrice
from .values import PriceQuote


@dataclass(frozen=True)
class Journey:
    due_now: PriceQuote
    later: PriceQuote

    @property
    def total(self) -> int:
        return self.due_now.total + self.later.total


class JourneyQuote:
    def __init__(self, quoter: PriceQuoter | None = None):
        self.quoter = quoter or PriceQuoter()

    def of(self, action, size) -> Journey:
        due_now = self.quoter.quote(action, size)
        return Journey(due_now, self._later(action, size))

    def _later(self, action, size) -> PriceQuote:
        if action != MeteredAction.LESSON_CREATE:
            return PriceQuote()
        facts = LessonCreatePrice(self.quoter.book).facts(size)
        if facts.entry != "diagnostic":
            return PriceQuote()  # a self-rated lesson or a quiz result has no Quick check: it is all paid now
        after = {"choice": "lesson"} if facts.intent == "lesson" else {"choice": "sheets_only", "sheets": facts.sheets}
        return self.quoter.quote(MeteredAction.LESSON_CONTINUE, after)

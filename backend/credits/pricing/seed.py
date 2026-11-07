"""The plan's prices (docs/archive/credits-implementation-plan.md §5.4) as data, and how they get into the
table.

Migration `0004_price_seed` seeds them once. `PriceSeed` is the same list for the code that needs it again: the test
fixtures (a test that flushes the database takes the migration's rows with it) and a database that lost them.
"""

from ..clock import Clock, SystemClock
from ..models import ActionPrice


class PriceSeed:
    PRICES = {
        "lesson.check": 3,
        "lesson.check_recommended": 2,
        "lesson.full": 10,
        "lesson.full_recommended": 9,
        "lesson.full_from_quiz": 9,
        "lesson.rest": 7,
        "sheets.after_check": 2,
        "sheets.after_check_single": 0,
        "sheet.each": 2,
        "sheet.grounded_extra": 1,
        "followup.foundation": 5,
        "followup.advanced": 7,
        "test.retake": 2,
        "quiz.tier_5": 1,
        "quiz.tier_10": 2,
        "quiz.tier_20": 3,
        "quiz.extra": 1,
        "streak.repair": 1,
    }
    #: in the learner's words; they are the lines of a quote and of a reserve
    LABELS = {
        "lesson.check": "Quick check",
        "lesson.check_recommended": "Quick check (recommended lesson)",
        "lesson.full": "Your lesson",
        "lesson.full_recommended": "Your lesson (recommended)",
        "lesson.full_from_quiz": "Lesson from your quiz result",
        "lesson.rest": "Your lesson, after the Quick check",
        "sheets.after_check": "Both study sheets, after the Quick check",
        "sheets.after_check_single": "One study sheet, after the Quick check",
        "sheet.each": "Study sheet",
        "sheet.grounded_extra": "Built from your lesson's pages",
        "followup.foundation": "Foundation lesson",
        "followup.advanced": "Advanced lesson",
        "test.retake": "Take the test again with new questions",
        "quiz.tier_5": "Quick quiz, 5 questions",
        "quiz.tier_10": "Quick quiz, 10 or 15 questions",
        "quiz.tier_20": "Quick quiz, 20 to 30 questions",
        "quiz.extra": "Quiz from your lessons, or with a warm-up",
        "streak.repair": "Repair a missed day",
    }

    def __init__(self, clock: Clock | None = None):
        self.clock = clock or SystemClock()

    def apply(self) -> int:
        """Add the prices that have no row at all (live or not), and nothing else: a price an administrator edited or
        switched off is left as it is. → how many were added."""
        known = set(ActionPrice.objects.values_list("key", flat=True))
        missing = [key for key in self.PRICES if key not in known]
        ActionPrice.objects.bulk_create(
            [
                ActionPrice(
                    key=key, credits=self.PRICES[key], label=self.LABELS[key], active=True, updated_at=self.clock.now()
                )
                for key in missing
            ]
        )
        if missing:
            from .book import PriceBook

            PriceBook.clear()
        return len(missing)

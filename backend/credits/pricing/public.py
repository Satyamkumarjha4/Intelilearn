"""What a visitor who is not signed in may be told about prices (the landing page's pricing section).

The page holds no number of its own. Everything here is read from the rows the checkout and the credit gate read
(`Plan`, `ActionPrice`, `CreditSettings`) and priced by the gate's own rules (`PriceRules`), so a price edited in the
console is the price on the page, and "about N lessons" is worked out once, here, rounded down. A price with no live
row is `None` (never shown, never free) and does not stop the rest being shown. Cached for a minute; every save of a
price, a plan or the settings clears it (credits/signals.py).
"""

from itertools import product

from django.core.cache import cache

from lessons.models import FlowSettings

from ..models import CreditSettings, Plan
from ..refusals import PriceUnavailable
from .book import PriceBook
from .rules import QUIZ_COUNTS, SOURCES, LessonCreatePrice, QuizCreatePrice, SheetGeneratePrice, TestRetakePrice

QUIZ_LEVEL_MODES = ("self_rating", "calibration", "existing_score")
QUICK_CHECK_BANDS = 5  # a Quick check asks the same number of questions in each of the five difficulty bands


class PublicPricing:
    CACHE_KEY = "public:pricing"
    TTL_S = 60

    def __init__(self, book: PriceBook | None = None):
        self.book = book or PriceBook()

    def payload(self) -> dict:
        body = cache.get(self.CACHE_KEY)
        if body is None:
            body = self._build()
            cache.set(self.CACHE_KEY, body, self.TTL_S)
        return body

    @classmethod
    def clear(cls) -> None:
        cache.delete(cls.CACHE_KEY)

    # --- building --------------------------------------------------------------------------------------------------

    def _build(self) -> dict:
        settings = CreditSettings.load()
        lesson = self._total(LessonCreatePrice(self.book), {"entry": "self_rating"})
        plans = list(Plan.objects.filter(active=True))
        one_time = next((plan for plan in plans if plan.is_one_time), None)
        return {
            "plans": [self._plan(plan, lesson) for plan in plans if not plan.is_one_time],
            "one_time": self._one_time(one_time, settings),
            "signup_credits": settings.signup_credits,
            "signup_about_lessons": self._lessons(settings.signup_credits, lesson),
            "daily_credits": settings.daily_credits,
            "weekly_streak_bonus": settings.weekly_streak_bonus,
            "monthly_streak_bonus": settings.monthly_streak_bonus,
            "bonus_valid_days": settings.bonus_valid_days,
            "lesson_credits": lesson,
            "retake_credits": self._total(TestRetakePrice(self.book), {}),
            "sheet_credits": self._range(
                SheetGeneratePrice(self.book),
                ({"sheets": 1, "grounding": grounding} for grounding in ("none", "lesson")),
            ),
            "quick_check_questions": FlowSettings.load().diagnostic_questions_per_band * QUICK_CHECK_BANDS,
            "quiz_credits": self._range(
                QuizCreatePrice(self.book),
                (
                    {"num_questions": count, "source_type": source, "level_mode": mode}
                    for count, source, mode in product(QUIZ_COUNTS, SOURCES, QUIZ_LEVEL_MODES)
                ),
            ),
        }

    def _plan(self, plan: Plan, lesson: int | None) -> dict:
        return {
            "key": plan.key,
            "name": plan.name,
            "credits": plan.credits,
            "period_days": plan.period_days,
            "price_paise": plan.price_paise,
            "max_quantity": plan.max_quantity,
            "price_paise_per_credit": round(plan.price_paise / plan.credits, 2) if plan.credits else None,
            "about_lessons": self._lessons(plan.credits, lesson),
        }

    @staticmethod
    def _one_time(plan: Plan | None, settings: CreditSettings) -> dict | None:
        if plan is None:
            return None
        return {
            "price_paise_per_credit": plan.price_paise,
            "min_credits": settings.min_one_time_credits,
            "max_credits": settings.max_one_time_credits,
            "valid_days": settings.purchased_valid_days,
        }

    @staticmethod
    def _lessons(credits: int, lesson: int | None) -> int | None:
        """Whole lessons the credits pay for, rounded down. None when a lesson has no price or a free one."""
        return credits // lesson if lesson else None

    @staticmethod
    def _total(rule, size: dict) -> int | None:
        try:
            return rule.quote(size).total
        except PriceUnavailable:
            return None

    def _range(self, rule, sizes) -> dict | None:
        totals = [self._total(rule, size) for size in sizes]
        if not totals or None in totals:
            return None
        return {"min": min(totals), "max": max(totals)}

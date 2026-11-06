"""A price as the API answers it, whether it was asked for by an action and its hints or read from a stopped run."""

from .exempt import ExemptPolicy
from .pricing.journey import Journey
from .pricing.values import PriceQuote


class QuoteAnswer:
    @staticmethod
    def of(action: str, journey: Journey, user) -> dict:
        return {
            "action": action,
            "lines": journey.due_now.as_json(),
            "due_now": journey.due_now.total,
            "later_lines": journey.later.as_json(),
            "later": journey.later.total,
            "total": journey.total,
            "exempt": ExemptPolicy().applies_to(user),
        }

    @classmethod
    def free(cls, action: str, user) -> dict:
        """Nothing is due: the answer of an action whose work was kept."""
        return cls.of(action, Journey(PriceQuote(), PriceQuote()), user)

"""What a purchase costs and gives, decided on the server (credits plan T20, D1). The client names a plan and a
quantity (or
an amount of credits for one-time credits); it never names a price. Every rule about what may be bought is here."""

from dataclasses import dataclass

from .errors import InvalidPlanRequest


@dataclass(frozen=True)
class PlanTerms:
    """A plan as the rules see it (made from a `Plan` row)."""

    key: str
    name: str
    credits: int  # each period's credits (0 for one-time credits)
    period_days: int
    price_paise: int  # a week, a month, or for one-time credits one credit
    max_quantity: int
    one_time: bool


@dataclass(frozen=True)
class PricedPurchase:
    plan: PlanTerms
    quantity: int
    credits: int  # the one-time amount bought (0 for a plan)
    amount_paise: int
    periods: int  # how many periods it makes


class PlanPricing:
    def price(self, plan: PlanTerms, *, quantity=1, credits=None, minimum: int, maximum: int) -> PricedPurchase:
        """What a purchase of `plan` costs, or `InvalidPlanRequest`. Whole numbers only: paise and credits."""
        if plan.one_time:
            return self._one_time(plan, quantity, credits, minimum, maximum)
        if credits is not None:
            raise InvalidPlanRequest(f"{plan.name} is bought by the number of periods, not an amount of credits.")
        if not self._whole(quantity) or not 1 <= quantity <= plan.max_quantity:
            raise InvalidPlanRequest(f"You can buy {plan.name} from 1 to {plan.max_quantity} at a time.")
        return PricedPurchase(plan, quantity, 0, quantity * plan.price_paise, quantity)

    def _one_time(self, plan, quantity, credits, minimum, maximum) -> PricedPurchase:
        if quantity != 1 or isinstance(quantity, bool):
            raise InvalidPlanRequest("One-time credits are bought once at a time.")
        if not self._whole(credits) or not minimum <= credits <= maximum:
            raise InvalidPlanRequest(f"Buy from {minimum} to {maximum} credits at a time.")
        return PricedPurchase(plan, 1, credits, credits * plan.price_paise, 0)

    @staticmethod
    def _whole(value) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

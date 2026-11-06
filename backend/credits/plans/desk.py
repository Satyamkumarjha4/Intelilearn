"""Opening a purchase (credits plan T20): the desk where a plan, a quantity or an amount becomes a `PlanPurchase`.

The server decides everything: the plan must exist and be on, the quantity or amount must be allowed, the price is
computed
from the plan table, and the queue must have room. Nothing is granted here; a purchase opens `pending` and is
fulfilled by
`PlanFulfilment` (when a payment is verified, or when an administrator gives the plan). The queue limit is checked
now, so a
payment is never taken for a purchase that cannot be fulfilled; it is not checked again at fulfilment, so a payment
that was
taken is always honoured (a few pending orders at once can overshoot the limit by the most that may be pending).
"""

import uuid

from django.db import transaction

from ..ledger import Ledger
from ..models import CreditSettings, Plan, PlanPeriod, PlanPurchase
from .errors import InvalidPlanRequest, QueueFull
from .pricing import PlanPricing, PlanTerms


class PurchaseDesk:
    def __init__(self, ledger: Ledger | None = None, pricing: PlanPricing | None = None):
        self.ledger = ledger or Ledger()
        self.pricing = pricing or PlanPricing()

    def open(
        self, user, plan_key: str, *, quantity=1, credits=None, source: str = PlanPurchase.Source.PAYMENT,
        by: str = "", reason: str = "", purchase_id=None,
    ) -> PlanPurchase:  # fmt: skip
        """A pending purchase of `plan_key`, or the one already opened under `purchase_id`. An administrator's gift
        (`source="admin"`) costs nothing, needs a reason and says who gave it."""
        if purchase_id is not None and (existing := PlanPurchase.objects.filter(pk=purchase_id).first()):
            return existing
        plan = Plan.objects.filter(key=plan_key, active=True).first()
        if plan is None:
            raise InvalidPlanRequest("That plan is not available.", "invalid_plan")
        settings = CreditSettings.load()
        priced = self.pricing.price(
            self.terms_of(plan), quantity=quantity, credits=credits,
            minimum=settings.min_one_time_credits, maximum=settings.max_one_time_credits,
        )  # fmt: skip
        meta, amount = {}, priced.amount_paise
        if source == PlanPurchase.Source.ADMIN:
            if not reason.strip():
                raise InvalidPlanRequest("Say why the plan is being given.", "invalid_reason")
            meta = {"reason": reason.strip(), "by": by, "list_amount_paise": amount}
            amount = 0
        with transaction.atomic(), self.ledger.exclusive(user):
            self._check_room(user, priced.periods, settings.max_queued_periods)
            return PlanPurchase.objects.create(
                id=purchase_id or uuid.uuid4(), user_id=getattr(user, "pk", user), plan=plan, quantity=priced.quantity,
                credits=priced.credits, amount_paise=amount, source=source, meta=meta,
                created_at=self.ledger.clock.now(),
            )  # fmt: skip

    @staticmethod
    def _check_room(user, new_periods: int, limit: int) -> None:
        if new_periods:
            open_periods = PlanPeriod.objects.filter(
                user_id=getattr(user, "pk", user), status__in=[PlanPeriod.Status.QUEUED, PlanPeriod.Status.ACTIVE]
            ).count()
            if open_periods + new_periods > limit:
                raise QueueFull(open_periods, limit)

    @staticmethod
    def terms_of(plan: Plan) -> PlanTerms:
        return PlanTerms(
            plan.key, plan.name, plan.credits, plan.period_days, plan.price_paise, plan.max_quantity, plan.is_one_time
        )

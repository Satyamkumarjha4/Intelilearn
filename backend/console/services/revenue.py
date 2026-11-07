"""Revenue beside model cost, in rupees (credits plan T31, §10).

Paid is what orders paid in the range took; refunded is what refund and dispute events took back in it; net is the two
apart. Model cost is recorded in dollars (`ModelCall.cost`), so it is turned into rupees at `USD_INR_RATE`, and the rate
is part of the answer so nobody has to guess which one made the figure. Money is exact: whole paise until the last step.
"""

from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Sum

from console.periods import Period
from llm_registry.models import ModelCall
from payments.gateway import PaymentEvent
from payments.models import PaymentEventLog, PaymentOrder

PAISE = Decimal(100)
CENTS = Decimal("0.01")


class RevenueReport:
    PAID = (PaymentOrder.Status.PAID, PaymentOrder.Status.FULFILLED)
    TAKEN_BACK = (PaymentEvent.REFUNDED, PaymentEvent.DISPUTED)

    def build(self, period: Period) -> dict:
        rate = Decimal(str(settings.USD_INR_RATE))
        orders = PaymentOrder.objects.filter(status__in=self.PAID, paid_at__gte=period.start, paid_at__lte=period.end)
        paid = orders.aggregate(paise=Sum("amount_paise"), count=Count("id"))
        refunds = PaymentEventLog.objects.filter(
            kind__in=self.TAKEN_BACK,
            outcome=PaymentEventLog.Outcome.APPLIED,
            received_at__gte=period.start,
            received_at__lte=period.end,
        ).aggregate(paise=Sum("amount_paise"))
        cost = ModelCall.objects.filter(created_at__gte=period.start, created_at__lte=period.end).aggregate(
            usd=Sum("cost")
        )
        paid_paise, refunded_paise = paid["paise"] or 0, refunds["paise"] or 0
        net_paise = paid_paise - refunded_paise
        cost_usd = Decimal(cost["usd"] or 0)
        cost_rupees = (cost_usd * rate).quantize(CENTS)
        return {
            "range": period.key,
            "period": {"start": period.start, "end": period.end},
            "orders": paid["count"] or 0,
            "paid": self._rupees(paid_paise),
            "refunded": self._rupees(refunded_paise),
            "net": self._rupees(net_paise),
            "model_cost_usd": str(cost_usd.quantize(Decimal("0.0001"))),
            "model_cost": str(cost_rupees),
            "after_model_cost": str((Decimal(net_paise) / PAISE - cost_rupees).quantize(CENTS)),
            "usd_inr_rate": str(rate),
        }

    @staticmethod
    def _rupees(paise: int) -> str:
        return str((Decimal(paise) / PAISE).quantize(CENTS))

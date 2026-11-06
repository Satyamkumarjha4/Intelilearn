"""Starting a period's credits when the period starts, and marking the periods that are over (credits plan T14, T19,
§5.7).

Credits are never granted before their period begins, so three weeks bought today drip one week at a time; and they are
spendable the instant a period begins, so this runs **inside every movement of the wallet**, under the wallet's lock
(the
`Ledger` calls `start_due` before it does anything else). The hourly job only sweeps the learners nobody has touched.
Both
are harmless to repeat: a period gets its bucket once (its status and the ledger key `period:<id>` see to that).

A period that passed while nobody looked is granted and then written off, in order, by the ledger's own expiry: its
bucket is
made with its real expiry, which is already behind, and the next step of the movement expires it. So the history says
what
happened, and the books still add up.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from django.db.models import Q

from ..models import CreditBucket, CreditTransaction, PlanPeriod

logger = logging.getLogger(__name__)

Type = CreditTransaction.Type


@dataclass(frozen=True)
class SweepReport:
    learners: int = 0  # learners whose periods moved
    started: int = 0
    ended: int = 0
    failures: tuple = field(default=())  # learners whose sweep raised


class PeriodActivator:
    def due(self, user_id, now: datetime):
        """The learner's periods that need a step: queued ones whose time has come, active ones that are over."""
        return PlanPeriod.objects.filter(user_id=user_id).filter(
            Q(status=PlanPeriod.Status.QUEUED, starts_at__lte=now)
            | Q(status=PlanPeriod.Status.ACTIVE, ends_at__lte=now)
        )

    def has_due(self, user_id, now: datetime) -> bool:
        return self.due(user_id, now).exists()

    def start_due(self, books, new_bucket) -> None:
        """Called by the ledger with the wallet locked. Starts what is due, in order, and counts it on `books`."""
        for period in self.due(books.user_id, books.now).select_for_update().order_by("starts_at", "position"):
            if period.status == PlanPeriod.Status.QUEUED:
                self._start(period, books, new_bucket)
            if period.ends_at <= books.now:
                period.status = PlanPeriod.Status.ENDED
                period.save(update_fields=["status"])
                books.periods_ended += 1

    @staticmethod
    def _start(period: PlanPeriod, books, new_bucket) -> None:
        bucket: CreditBucket = new_bucket(books, CreditBucket.Source.SUBSCRIPTION, period.credits, period.ends_at,
                                          period.purchase_id)  # fmt: skip
        books.post(
            Type.GRANT, period.credits, f"period:{period.pk}",
            allocations=[{"bucket": str(bucket.pk), "amount": period.credits}],
            meta={"source": "subscription", "period": str(period.pk), "purchase": str(period.purchase_id)},
        )  # fmt: skip
        period.bucket = bucket
        period.status = PlanPeriod.Status.ACTIVE
        period.save(update_fields=["bucket", "status"])
        books.periods_started += 1

    def sweep(self, ledger) -> SweepReport:
        """For the hourly job: step every learner who has something due. Each learner is its own transaction, so one
        failing
        stops no one."""
        now = ledger.clock.now()
        due = PlanPeriod.objects.filter(
            Q(status=PlanPeriod.Status.QUEUED, starts_at__lte=now)
            | Q(status=PlanPeriod.Status.ACTIVE, ends_at__lte=now)
        )
        learners = list(due.order_by().values_list("user_id", flat=True).distinct())
        moved = started = ended = 0
        failures = []
        for learner in learners:
            try:
                s, e = ledger.activate_periods(learner)
            except Exception:
                logger.exception("Could not step the plan periods of user %s", learner)
                failures.append(learner)
                continue
            if s or e:
                moved += 1
                started += s
                ended += e
        return SweepReport(moved, started, ended, tuple(failures))

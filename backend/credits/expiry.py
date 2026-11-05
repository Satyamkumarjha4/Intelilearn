"""Writing off lapsed buckets for everyone: the work of the hourly job (credits plan T14, scheduled in phase 10.3).

A lapsed bucket is already unspendable: the balance and every movement leave it out. This pass makes the books say so
for learners who have not moved lately. Each learner is written off through `Ledger.expire_due` in its own
transaction, so
one failure stops nothing else and a repeat finds nothing to do.
"""

import logging
from dataclasses import dataclass, field

from .ledger import Ledger
from .models import CreditBucket

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpiryReport:
    learners: int = 0  # learners with at least one bucket written off
    buckets: int = 0
    credits: int = 0
    failures: tuple = field(default=())  # learners whose write-off raised


class ExpiryService:
    def __init__(self, ledger: Ledger | None = None):
        self.ledger = ledger or Ledger()

    def run(self) -> ExpiryReport:
        due = CreditBucket.objects.filter(amount_remaining__gt=0, expires_at__lte=self.ledger.clock.now())
        learners = list(due.order_by("user_id").values_list("user_id", flat=True).distinct())
        written = buckets = credits = 0
        failures = []
        for learner in learners:
            try:
                moved = self.ledger.expire_due(learner)
            except Exception:
                logger.exception("Could not write off lapsed credits for user %s", learner)
                failures.append(learner)
                continue
            if moved:
                written += 1
                buckets += len(moved)
                credits += sum(-m.transaction.amount for m in moved)
        return ExpiryReport(written, buckets, credits, tuple(failures))

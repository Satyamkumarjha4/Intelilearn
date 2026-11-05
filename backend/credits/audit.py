"""The check on the ledger's one equation (credits plan T4): for every learner, the sum of their ledger rows equals the
sum of their buckets' `amount_remaining`, and the last row's `balance_after` is that same number.

A break means a credit was made or lost outside the ledger (a bug, or an edit behind its back). The audit only reads.
"""

from dataclasses import dataclass

from django.db.models import Sum

from .models import CreditBucket, CreditTransaction


@dataclass(frozen=True)
class AuditBreak:
    user_id: object
    ledger_sum: int
    bucket_sum: int
    last_balance: int  # `balance_after` of the learner's last row, 0 when there is none
    problems: tuple[str, ...]


@dataclass(frozen=True)
class AuditReport:
    checked: int
    breaks: tuple[AuditBreak, ...]

    @property
    def ok(self) -> bool:
        return not self.breaks


class LedgerAudit:
    def check(self, user) -> AuditReport:
        return self._report({getattr(user, "pk", user)})

    def check_all(self) -> AuditReport:
        learners = set(CreditTransaction.objects.order_by().values_list("user_id", flat=True).distinct())
        learners |= set(CreditBucket.objects.order_by().values_list("user_id", flat=True).distinct())
        return self._report(learners)

    def _report(self, learners: set) -> AuditReport:
        ledger = self._sums(CreditTransaction.objects, "amount", learners)
        buckets = self._sums(CreditBucket.objects, "amount_remaining", learners)
        last = dict(
            CreditTransaction.objects.filter(user_id__in=learners)
            .order_by("user_id", "-id")
            .distinct("user_id")
            .values_list("user_id", "balance_after")
        )
        breaks = []
        for learner in sorted(learners, key=str):
            ledger_sum, bucket_sum, last_balance = ledger.get(learner, 0), buckets.get(learner, 0), last.get(learner, 0)
            problems = []
            if ledger_sum != bucket_sum:
                problems.append(f"the ledger rows add up to {ledger_sum} but the buckets hold {bucket_sum}")
            if last_balance != ledger_sum:
                problems.append(f"the last running balance is {last_balance} but the rows add up to {ledger_sum}")
            if problems:
                breaks.append(AuditBreak(learner, ledger_sum, bucket_sum, last_balance, tuple(problems)))
        return AuditReport(len(learners), tuple(breaks))

    @staticmethod
    def _sums(manager, column: str, learners: set) -> dict:
        rows = manager.filter(user_id__in=learners).values("user_id").annotate(total=Sum(column))
        return {row["user_id"]: row["total"] or 0 for row in rows.order_by()}

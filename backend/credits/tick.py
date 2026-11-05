"""The hourly job (credits plan T14, §5.9): write off lapsed buckets, release the reserves nothing will settle, and
check the
ledger. Correctness never waits for it (a lapsed bucket is already unspendable, a movement writes it off itself); it
makes the
books say so, lets stuck reserves go back, and notices a break within the hour.

Every part is harmless to repeat, and a part that fails is reported without stopping the others. A break in the
ledger is
logged as an error, not raised: the other parts still ran, and what the break is can be read in `manage.py
credits_audit`."""

import logging
from dataclasses import dataclass, field

from .audit import LedgerAudit
from .expiry import ExpiryService
from .ledger import Ledger
from .reconcile import HoldReconciler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TickReport:
    expired_buckets: int = 0
    expired_credits: int = 0
    released_holds: int = 0
    audit_breaks: int = 0
    failed: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "expired_buckets": self.expired_buckets,
            "expired_credits": self.expired_credits,
            "released_holds": self.released_holds,
            "audit_breaks": self.audit_breaks,
            "failed": list(self.failed),
        }


class HourlyTick:
    def __init__(self, ledger: Ledger | None = None, expiry=None, reconciler=None, audit: LedgerAudit | None = None):
        ledger = ledger or Ledger()
        self.expiry = expiry or ExpiryService(ledger)
        self.reconciler = reconciler or HoldReconciler(ledger)
        self.audit = audit or LedgerAudit()

    def run(self) -> TickReport:
        failed: list[str] = []
        expired = self._part("expiry", failed, self.expiry.run)
        reconciled = self._part("reconciler", failed, self.reconciler.run)
        audited = self._part("audit", failed, self.audit.check_all)
        breaks = audited.breaks if audited else ()
        for found in breaks:
            logger.error("Credit ledger break for user %s: %s", found.user_id, "; ".join(found.problems))
        return TickReport(
            expired_buckets=expired.buckets if expired else 0,
            expired_credits=expired.credits if expired else 0,
            released_holds=(reconciled.released_failed + reconciled.released_orphans) if reconciled else 0,
            audit_breaks=len(breaks),
            failed=failed,
        )

    @staticmethod
    def _part(name: str, failed: list, run):
        try:
            return run()
        except Exception:
            logger.exception("The hourly credits job could not run its %s part", name)
            failed.append(name)
            return None

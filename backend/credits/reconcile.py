"""Letting go of reserves nothing will settle (credits plan T13).

A reserve is settled by the run it belongs to. Two things leave one stuck: a run that ended in failure (or was
stopped) whose
settlement was lost, and a reserve taken for work whose rows were never made. This pass releases both. It never
releases a
reserve whose run is merely paused or still going: a paused run (a quiz waiting for the learner, perhaps for days) still
owes its work, so age alone is no reason to give it away.

Not scheduled yet (the hourly job arrives in 10.3); it is callable and safe to run twice.
"""

import logging
from dataclasses import dataclass, field

from lessons.metering import AuthorizationLedger, RunOutcome
from lessons.models import GraphRun

from .gate import CreditGate
from .ledger import Ledger
from .models import CreditHold

logger = logging.getLogger(__name__)

STILL_OWING = (GraphRun.Status.QUEUED, GraphRun.Status.RUNNING, GraphRun.Status.PAUSED)


@dataclass(frozen=True)
class ReconcileReport:
    released_failed: int = 0
    released_orphans: int = 0
    committed: int = 0
    left_alone: int = 0
    failures: tuple = field(default=())  # the reserves that could not be settled, by authorization id


class HoldReconciler:
    def __init__(self, ledger: Ledger | None = None, gate=None, authorizations: AuthorizationLedger | None = None):
        self.ledger = ledger or Ledger()
        self.gate = gate or CreditGate(ledger=self.ledger)
        self.authorizations = authorizations or AuthorizationLedger()

    def run(self) -> ReconcileReport:
        counts = {"released_failed": 0, "released_orphans": 0, "committed": 0, "left_alone": 0}
        failures = []
        now = self.ledger.clock.now()
        for hold in CreditHold.objects.filter(status=CreditHold.Status.HELD).order_by("created_at", "pk"):
            try:
                counts[self._reconcile(hold, now)] += 1
            except Exception:
                logger.exception("Could not reconcile the reserve %s", hold.pk)
                failures.append(str(hold.pk))
        return ReconcileReport(**counts, failures=tuple(failures))

    def _reconcile(self, hold: CreditHold, now) -> str:
        latest = GraphRun.objects.filter(payload__authorization__id=str(hold.pk)).order_by("-created_at").first()
        if latest is None:  # no run claims it: an orphan once its deadline has passed
            if hold.orphan_deadline is not None and hold.orphan_deadline <= now:
                self.ledger.release(hold.pk)
                return "released_orphans"
            return "left_alone"
        if latest.status in STILL_OWING:
            return "left_alone"
        outcome = {
            GraphRun.Status.SUCCEEDED: RunOutcome.SUCCEEDED,
            GraphRun.Status.CANCELLED: RunOutcome.CANCELLED,
        }.get(latest.status, RunOutcome.FAILED)
        self.authorizations.settle_once(latest.pk, outcome, self.gate.settle)
        if CreditHold.objects.get(pk=hold.pk).status == CreditHold.Status.HELD:
            # The run was already marked settled but the reserve is still open (the settlement was lost half way).
            self.gate.settle(self.authorizations.read(latest).authorization, outcome)
        return "committed" if outcome is RunOutcome.SUCCEEDED else "released_failed"

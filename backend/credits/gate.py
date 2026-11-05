"""The credit gate: the real `ActionGate` (docs/to_be_developed/credits-implementation-plan.md §5.2, §6.2).

`authorize` prices the action with the same `PriceQuoter` the quote endpoint uses, reserves that many credits (`Ledger`
`place_hold`) and answers with an `Authorization` whose id is the reserve's id, so the run it travels with can find the
reserve again. Every authorization makes a reserve, even for 0 credits, so free work is recorded too. The credits
leave the
wallet at once; `settle` keeps them spent (`succeeded`) or gives them back (`failed`, `cancelled`).

The price is the one at the moment of the ask and is stored on the reserve, so an edit to the price table never changes
work that is under way or what a failure gives back.

A repeated ask for the *same open work* (a double click, a retried request) returns the same authorization. The ask
for new
work with a key that was used before, because the earlier work was settled (another sheet for the same lesson), takes a
fresh reserve: the key is the ask's name, and a settled ask is finished.
"""

import logging
import uuid
from itertools import count

from lessons.metering import ActionContext, ActionGate, Authorization, MeteredAction, RunOutcome

from .errors import HoldConflict, HoldNotFound, HoldNotHeld, InsufficientBalance
from .exempt import ExemptPolicy
from .ledger import Ledger
from .models import CreditHold
from .pricing.quoter import PriceQuoter
from .refusals import ActionInProgress, InsufficientCredits

logger = logging.getLogger(__name__)

#: what the subject of each action is, so a history can name it
SUBJECT_KINDS = {
    MeteredAction.LESSON_CREATE: "lesson",
    MeteredAction.LESSON_CONTINUE: "lesson",
    MeteredAction.LESSON_FOLLOWUP: "lesson",
    MeteredAction.SHEET_GENERATE: "lesson",
    MeteredAction.TEST_RETAKE: "test_attempt",
    MeteredAction.QUIZ_CREATE: "quiz",
    MeteredAction.QUIZ_RETAKE: "quiz_attempt",
}


class CreditGate(ActionGate):
    def __init__(
        self, quoter: PriceQuoter | None = None, ledger: Ledger | None = None, exempt: ExemptPolicy | None = None
    ):
        self.quoter = quoter or PriceQuoter()
        self.ledger = ledger or Ledger()
        self.exempt = exempt or ExemptPolicy()

    def authorize(self, context: ActionContext) -> Authorization:
        quote = self.quoter.quote(context.action, context.size)
        exempt = self.exempt.applies_to(context.user)
        hold = self._reserve(context, 0 if exempt else quote.total, quote.as_json(), exempt)
        return Authorization(
            id=str(hold.pk),
            action=context.action,
            size=dict(context.size),
            resume=context.resume,
            completes_at=context.completes_at,
            meta={"credits": hold.amount, "lines": hold.lines, "exempt": hold.exempt},
            tracked=True,
        )

    def settle(self, authorization: Authorization, outcome: RunOutcome) -> None:
        try:
            hold_id = uuid.UUID(authorization.id)
            if outcome is RunOutcome.SUCCEEDED:
                self.ledger.commit(hold_id)
            else:
                self.ledger.release(hold_id)
        except HoldNotHeld:
            logger.info("Authorization %s was already settled; %s ignored.", authorization.id, outcome)
        except (HoldNotFound, ValueError):
            logger.warning("Authorization %s has no reserve here; %s ignored.", authorization.id, outcome)

    def _reserve(self, context: ActionContext, amount: int, lines: list, exempt: bool) -> CreditHold:
        for attempt in count():
            key = context.key if attempt == 0 else f"{context.key}#{attempt}"
            try:
                placed = self.ledger.place_hold(
                    context.user, amount, str(context.action), key,
                    subject_kind=SUBJECT_KINDS[context.action], subject_id=context.subject_id, lines=lines,
                    exempt=exempt,
                )  # fmt: skip
            except InsufficientBalance as short:
                raise InsufficientCredits(short.required, short.available) from None
            except HoldConflict:
                raise ActionInProgress() from None
            if placed.movement.created or placed.hold.status == CreditHold.Status.HELD:
                return placed.hold
            # The key belongs to work that is settled: this is new work, so it takes a reserve of its own.

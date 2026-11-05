"""Why the ledger refused a movement. These are domain errors, not HTTP ones: nothing calls the ledger from a view yet,
and the credit gate (phase 10.2) turns `InsufficientBalance` into the API's `402 insufficient_credits`."""


class LedgerError(Exception):
    """Base of every refusal by `Ledger`."""


class InvalidAmount(LedgerError):
    """An amount that cannot be moved: not a whole number, or zero or negative where it must be positive."""


class ReasonRequired(InvalidAmount):
    """An administrator's adjustment without the reason it was made for."""


class InsufficientBalance(LedgerError):
    def __init__(self, required: int, available: int):
        super().__init__(f"{required} credits are needed and {available} are available.")
        self.required = required
        self.available = available


class HoldConflict(LedgerError):
    """A different hold is already held for this action and subject."""


class HoldNotFound(LedgerError):
    pass


class HoldNotHeld(LedgerError):
    """A hold that was already settled the other way (committed, then released, or the reverse)."""


class KeyReused(LedgerError):
    """An idempotency key that belongs to another learner's movement."""


class AppendOnly(LedgerError):
    """An attempt to change or delete a ledger row."""

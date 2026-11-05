"""The refusals of the credit gate, as the API shows them. All are `ActionRefused`, so every screen that already
handles a
refused action handles these too; the frontend's `ActionRefusedMessage` reads the `402`'s `required` and `available`."""

from rest_framework import status

from lessons.metering import ActionRefused


def credits_word(count: int) -> str:
    return f"{count} credit" if count == 1 else f"{count} credits"


class InsufficientCredits(ActionRefused):
    """The learner has too few credits for this. Nothing was created. `required` and `available` are whole credits."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "insufficient_credits"

    def __init__(self, required: int, available: int):
        super().__init__(f"You need {credits_word(required)} for this and have {available}.")
        self.required = required
        self.available = available
        self.extra = {"required": required, "available": available}


class PriceUnavailable(ActionRefused):
    """A price the table does not have. Never read as free: the action is refused until someone sets it."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "price_unavailable"
    default_detail = "Prices are not available right now. Please try again in a little while."

    def __init__(self, key: str = ""):
        super().__init__()
        self.key = key


class ActionInProgress(ActionRefused):
    """The same work is already under way and holds its credits."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "action_in_progress"
    default_detail = "That is already under way."

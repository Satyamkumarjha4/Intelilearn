"""Why a purchase of a plan was refused. API errors, so the checkout (phase 10.6) shows them as they are."""

from rest_framework import status
from rest_framework.exceptions import APIException


class InvalidPlanRequest(APIException):
    """A plan, quantity or amount the server will not sell. `invalid_plan` is the plan, `invalid_amount` the number of
    weeks or credits, `invalid_reason` an administrator's missing reason."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_amount"
    default_detail = "That cannot be bought."

    def __init__(self, detail: str, code: str = "invalid_amount"):
        super().__init__(detail, code)
        self.code = code


class QueueFull(APIException):
    """Too many periods are open (running or waiting) to add more."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "queue_full"
    default_detail = "You have as many plans lined up as you can. Try again once some have run."

    def __init__(self, open_periods: int, limit: int):
        super().__init__()
        self.extra = {"open_periods": open_periods, "limit": limit}

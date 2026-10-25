"""Why a console request was refused, beyond what the lessons API already says. Each is an `APIException`, so the API
turns it into `{detail, code}` itself."""

from rest_framework import status
from rest_framework.exceptions import APIException


class NotRetryable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "not_retryable"
    default_detail = "Only a lesson build can be retried from here."


class ModelInUse(APIException):
    """A model that steps still use cannot be deleted. The steps are in the body, so a screen can list them."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "model_in_use"

    def __init__(self, model_label: str, nodes: list[str]):
        super().__init__(f"{model_label} is used by {', '.join(nodes)}. Take it out of those steps first.")
        self.extra = {"nodes": nodes}

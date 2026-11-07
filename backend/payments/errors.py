"""Why a payment step did not happen. Two kinds: domain errors a gateway raises (`NotSupported`, `InvalidWebhook`,
`GatewayUnavailable`), and API errors the checkout shows as they are (`GatewayNotEnabled`, `TooManyPending`,
`GatewayDown`)."""

from rest_framework import status
from rest_framework.exceptions import APIException


class PaymentError(Exception):
    """Base of what a gateway raises."""


class NotSupported(PaymentError):
    """The gateway does not offer this (a refund, say)."""


class InvalidWebhook(PaymentError):
    """A bad signature, an old timestamp or a body that cannot be read. Nothing about the call may be trusted."""


class GatewayUnavailable(PaymentError):
    """The provider could not be reached or answered with an error."""


class GatewayRejected(GatewayUnavailable):
    """The provider was reached and refused the request (a bad key, a bad parameter, a refund too large). Nothing is
    gained by trying again unchanged. It is still an unavailable checkout to whoever was buying, so callers that
    handle `GatewayUnavailable` handle this too."""


class GatewayNotEnabled(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "gateway_not_enabled"
    default_detail = "That way of paying is not available."


class TooManyPending(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "too_many_pending"
    default_detail = "You have payments that are still being confirmed. Wait for them before starting another."


class GatewayDown(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "gateway_unavailable"
    default_detail = "We couldn't reach the payment service. Nothing was charged. Please try again in a moment."


class WebhookRefused(APIException):
    """The callback was not proved to come from the provider."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_webhook"
    default_detail = "The callback could not be verified."


class BodyTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_code = "body_too_large"
    default_detail = "The callback is too large."

from rest_framework import exceptions
from rest_framework.views import exception_handler


class ApiErrorFormatter:
    """Every API error has the same shape: {"detail": str, "code": str, "fields"?: {field: [messages]}}."""

    FIELDS_DETAIL = "Please correct the highlighted fields."

    def format(self, exc, response):
        if isinstance(exc, exceptions.ValidationError):
            response.data = self._validation_error(exc)
        else:
            response.data = self._error(exc, response)
        return response

    def _validation_error(self, exc: exceptions.ValidationError) -> dict:
        data = exc.detail if isinstance(exc.detail, dict) else {"non_field_errors": exc.detail}
        fields = {
            key: [str(message) for message in (value if isinstance(value, list) else [value])]
            for key, value in data.items()
        }
        general = fields.pop("non_field_errors", None)
        body = {"detail": general[0] if general else self.FIELDS_DETAIL, "code": "invalid"}
        if fields:
            body["fields"] = fields
        return body

    @staticmethod
    def _error(exc, response) -> dict:
        detail = response.data.get("detail", str(exc)) if isinstance(response.data, dict) else str(exc)
        codes = exc.get_codes() if isinstance(exc, exceptions.APIException) else "error"
        code = codes.get("detail", "error") if isinstance(codes, dict) else codes
        return {"detail": str(detail), "code": str(code)}


def api_exception_handler(exc, context):
    """REST_FRAMEWORK["EXCEPTION_HANDLER"] hook: DRF's handler, then ApiErrorFormatter for the shape."""
    response = exception_handler(exc, context)
    return None if response is None else ApiErrorFormatter().format(exc, response)

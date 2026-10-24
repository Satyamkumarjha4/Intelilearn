from rest_framework import exceptions
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    """Every API error has the same shape: {"detail": str, "code": str, "fields"?: {field: [messages]}}."""
    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, exceptions.ValidationError):
        data = exc.detail if isinstance(exc.detail, dict) else {"non_field_errors": exc.detail}
        fields = {
            key: [str(message) for message in (value if isinstance(value, list) else [value])]
            for key, value in data.items()
        }
        general = fields.pop("non_field_errors", None)
        response.data = {
            "detail": general[0] if general else "Please correct the highlighted fields.",
            "code": "invalid",
        }
        if fields:
            response.data["fields"] = fields
        return response

    detail = response.data.get("detail", str(exc)) if isinstance(response.data, dict) else str(exc)
    codes = exc.get_codes() if isinstance(exc, exceptions.APIException) else "error"
    code = codes.get("detail", "error") if isinstance(codes, dict) else codes
    response.data = {"detail": str(detail), "code": str(code)}
    return response

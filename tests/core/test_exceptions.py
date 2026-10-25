"""Unit under test: `core.exceptions.ApiErrorFormatter` and the `api_exception_handler` hook DRF calls with it.

Why: the frontend's ApiClient reads `detail`, `code` and `fields` from every error. A different shape would show
users a generic "Request failed" instead of the real message, or lose the per-field errors on a form.

Use cases:
- field validation errors become "fields" with a generic detail and code "invalid"
- a non-field validation error becomes the detail
- other API errors keep their detail and code
- an error that carries extra fields (`extra`) sends them next to the detail and code
- errors DRF doesn't handle are left to Django (None)
"""

from django.http import Http404
from rest_framework import exceptions

from core.exceptions import ApiErrorFormatter, api_exception_handler


def handle(exc):
    response = api_exception_handler(exc, {})
    return response.status_code, response.data


def test_field_errors_become_fields():
    status, body = handle(exceptions.ValidationError({"email": ["Taken."], "password": "Too short."}))

    assert status == 400
    assert body == {"detail": ApiErrorFormatter.FIELDS_DETAIL, "code": "invalid",
                    "fields": {"email": ["Taken."], "password": ["Too short."]}}  # fmt: skip


def test_a_non_field_error_becomes_the_detail():
    _, body = handle(exceptions.ValidationError({"non_field_errors": ["Passwords don't match."]}))

    assert body == {"detail": "Passwords don't match.", "code": "invalid"}


def test_other_api_errors_keep_their_detail_and_code():
    assert handle(exceptions.NotAuthenticated()) == (
        401,
        {"detail": "Authentication credentials were not provided.", "code": "not_authenticated"},
    )
    assert handle(Http404())[0] == 404


def test_an_error_with_extra_fields_sends_them_next_to_the_detail_and_code():
    class Conflict(exceptions.APIException):
        status_code = 409
        default_code = "already_done"
        default_detail = "Done."

        def __init__(self):
            super().__init__()
            self.extra = {"id": "abc"}

    assert handle(Conflict()) == (409, {"detail": "Done.", "code": "already_done", "id": "abc"})


def test_errors_drf_does_not_handle_are_left_to_django():
    assert api_exception_handler(ValueError("boom"), {}) is None

"""Unit under test: `accounts.mail.brevo.BrevoMailer`, the adapter for Brevo's transactional email API.

Why: Brevo carries every sign-up code at launch (its free plan, phase 11 D2). The request must match Brevo's own
reference
(endpoint, the `api-key` header, `sender`, `to`, `subject`, `htmlContent`, `textContent`), a provider outage must
retry and a
refusal must not, and the API key must never be printed or logged. Run against `httpx.MockTransport`: no test calls
Brevo.
Which statuses are retryable is our rule (rate limit and server errors retry, other refusals do not); Brevo's reference
page names only the 400 body (`code`, `message`) and the 201 reply (`messageId`).

Use cases:
- a message is POSTed to https://api.brevo.com/v3/smtp/email with the `api-key` header, the sender, the recipient, the
  subject, the HTML and the text; the reply's `messageId` is returned
- a message with no HTML part is sent with its text as the HTML (Brevo requires one)
- a 429, a 5xx, a timeout and a connection error are transient (retry)
- a 400, 401 or 403 is permanent, and says Brevo's error `code`, never the body or the key; with no usable `code`
  (none, or
  free text) it says only the status
- the sender is read from `MAIL_FROM` ("Socra <no-reply@domain>") and the key from `BREVO_API_KEY`; a missing key
  or sender is
  reported by `missing_config`
- the API key appears in no error message and no repr
"""

import json

import httpx
import pytest

from accounts.mail.brevo import BrevoMailer
from accounts.mail.mailer import MailMessage, PermanentMailError, TransientMailError

KEY = "xkeysib-test-0123456789"
MESSAGE = MailMessage(
    to="ada@example.com", kind="signup_code", subject="Your Socra code", text="Code 123456", html="<p>Code 123456</p>"
)


def mailer(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return BrevoMailer(api_key=KEY, sender="Socra <no-reply@socra.example>", client=client, **kwargs)


def test_a_message_is_posted_the_way_brevos_reference_says():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(
            url=str(request.url), method=request.method, headers=request.headers, body=json.loads(request.content)
        )
        return httpx.Response(201, json={"messageId": "<201798300811.5787683@relay.example>"})

    result = mailer(handler).send(MESSAGE)

    assert (seen["method"], seen["url"]) == ("POST", "https://api.brevo.com/v3/smtp/email")
    assert seen["headers"]["api-key"] == KEY and seen["headers"]["content-type"] == "application/json"
    assert seen["body"] == {
        "sender": {"name": "Socra", "email": "no-reply@socra.example"},
        "to": [{"email": "ada@example.com"}],
        "subject": "Your Socra code",
        "htmlContent": "<p>Code 123456</p>",
        "textContent": "Code 123456",
    }
    assert result.message_id == "<201798300811.5787683@relay.example>"


def test_a_message_with_no_html_is_sent_with_its_text_as_the_html():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={"messageId": "m1"})

    mailer(handler).send(MailMessage(to="a@example.com", kind="x", subject="S", text="Line <1>\nLine 2"))

    assert "&lt;1&gt;" in seen["htmlContent"] and "Line 2" in seen["htmlContent"]


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_a_rate_limit_or_a_server_error_is_transient(status):
    with pytest.raises(TransientMailError):
        mailer(lambda request: httpx.Response(status, json={"message": "later"})).send(MESSAGE)


@pytest.mark.parametrize(
    "failure", [httpx.ConnectTimeout("slow"), httpx.ConnectError("down"), httpx.ReadTimeout("slow")]
)
def test_a_timeout_or_a_connection_error_is_transient(failure):
    def handler(request):
        raise failure

    with pytest.raises(TransientMailError):
        mailer(handler).send(MESSAGE)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_a_refusal_is_permanent_and_names_the_code_not_the_body(status):
    body = {"code": "invalid_parameter", "message": "to: ada@example.com is not valid 123456"}

    with pytest.raises(PermanentMailError) as raised:
        mailer(lambda request: httpx.Response(status, json=body)).send(MESSAGE)

    assert "invalid_parameter" in str(raised.value)
    assert "123456" not in str(raised.value) and "ada@example.com" not in str(raised.value)


@pytest.mark.parametrize(
    "body",
    [
        {"message": "to: ada@example.com 123456"},
        {"code": "to ada@example.com, code 123456: " + "x" * 80},
        {"code": 42},
        ["ada@example.com"],
    ],
)
def test_a_refusal_with_no_usable_code_says_only_the_status(body):
    with pytest.raises(PermanentMailError) as raised:
        mailer(lambda request: httpx.Response(400, json=body)).send(MESSAGE)

    assert str(raised.value) == "Brevo refused it: HTTP 400"


def test_a_refusal_with_no_json_body_is_still_permanent():
    with pytest.raises(PermanentMailError):
        mailer(lambda request: httpx.Response(403, text="<html>nope</html>")).send(MESSAGE)


def test_the_key_is_in_no_error_and_no_repr():
    with pytest.raises(PermanentMailError) as raised:
        mailer(lambda request: httpx.Response(401, json={"code": "unauthorized", "message": f"bad key {KEY}"})).send(
            MESSAGE
        )

    assert KEY not in str(raised.value) and KEY not in repr(raised.value)
    assert KEY not in repr(mailer(lambda request: httpx.Response(201)))


def test_the_sender_and_key_come_from_the_settings(settings):
    settings.BREVO_API_KEY, settings.MAIL_FROM = KEY, "Socra <no-reply@socra.example>"

    built = BrevoMailer.from_settings()

    assert built.missing_config() == []
    assert built.sender_email == "no-reply@socra.example" and built.sender_name == "Socra"


def test_a_missing_key_or_sender_is_reported(settings):
    settings.BREVO_API_KEY, settings.MAIL_FROM = "", ""

    assert BrevoMailer.from_settings().missing_config() == ["BREVO_API_KEY", "MAIL_FROM"]

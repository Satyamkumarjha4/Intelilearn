"""Unit under test: `accounts.abuse.captcha` (`TurnstileVerifier`, `NoCaptcha`, `CaptchaGate`), the sign-up challenge
that staff can switch on when abuse shows up (plan D14).

Why: the challenge is only worth having if a visitor who has not clearly passed it gets nowhere, and if it can never
lock everyone out by accident. So the verifier fails closed (any answer that is not a clear `success: true` is a
refusal, and a missing token never even reaches Cloudflare), the secret goes only in the request to Cloudflare, and the
gate reads the console's switch on every call. Cloudflare is an `httpx.MockTransport`: nothing here touches the
network.

Use cases:
- Turnstile is asked with the secret, the token and the visitor's address as a form, and `success: true` passes
- a failed answer, an error status, an answer that is not JSON, a network error, a missing, empty or over-long token and
  a missing secret are each a refusal; a token that is missing or too long never reaches Cloudflare
- Cloudflare's own words about why it refused (`error-codes`) are logged, never the token or the secret
- the verifier reports the settings it lacks
- with the switch off the gate passes everyone and asks nobody; with it on it refuses a visitor who did not pass,
  records the event, and passes one who did
- the switch is read on every call, so flipping it takes effect at once
- the public config says whether to show the widget and gives its key only when on
"""

import logging

import httpx
import pytest

from accounts.abuse.captcha import CaptchaFailed, CaptchaGate, NoCaptcha, TurnstileVerifier
from accounts.models import AuthEvent, AuthSettings

pytestmark = pytest.mark.django_db

SECRET = "turnstile-secret-never-in-a-log"


def verifier(answer, secret=SECRET):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer(request) if callable(answer) else answer

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TurnstileVerifier(secret, "site", http=client), seen


def ok():
    return httpx.Response(200, json={"success": True, "error-codes": [], "hostname": "example.com"})


def test_turnstile_is_asked_with_the_secret_the_token_and_the_address_as_a_form_and_success_passes():
    turnstile, seen = verifier(ok())

    assert turnstile.passes("token-123", "203.0.113.5") is True

    (request,) = seen
    assert str(request.url) == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    assert request.method == "POST" and "application/x-www-form-urlencoded" in request.headers["content-type"]
    assert dict(item.split("=", 1) for item in request.content.decode().split("&")) == {
        "secret": SECRET,
        "response": "token-123",
        "remoteip": "203.0.113.5",
    }


def test_the_address_is_left_out_when_there_is_none():
    turnstile, seen = verifier(ok())

    turnstile.passes("token", None)

    assert "remoteip" not in seen[0].content.decode()


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json={"success": False, "error-codes": ["invalid-input-response"]}),
        httpx.Response(200, json={"success": "true"}),
        httpx.Response(200, json={"success": 1}),
        httpx.Response(200, json={}),
        httpx.Response(200, json=["success"]),
        httpx.Response(400, json={"success": True}),
        httpx.Response(500, text="oops"),
        httpx.Response(200, text="<html>not json</html>"),
    ],
    ids=["failed", "string success", "number success", "empty", "a list", "error status", "server error", "not json"],
)
def test_anything_that_is_not_a_clear_success_true_is_a_refusal(answer):
    turnstile, _ = verifier(answer)

    assert turnstile.passes("token", "203.0.113.5") is False


def test_a_network_error_is_a_refusal_not_a_crash():
    def down(request):
        raise httpx.ConnectError("no route")

    turnstile, _ = verifier(down)

    assert turnstile.passes("token", "203.0.113.5") is False


@pytest.mark.parametrize("token", [None, "", 12345, "x" * 2049])
def test_a_missing_empty_or_over_long_token_never_reaches_cloudflare(token):
    turnstile, seen = verifier(ok())

    assert turnstile.passes(token, "203.0.113.5") is False
    assert seen == []


def test_a_token_of_exactly_the_longest_allowed_length_is_asked_about():
    turnstile, seen = verifier(ok())

    assert turnstile.passes("x" * 2048, None) is True and len(seen) == 1


def test_no_secret_is_a_refusal_and_asks_nobody(caplog):
    turnstile, seen = verifier(ok(), secret="")

    with caplog.at_level(logging.ERROR):
        assert turnstile.passes("token", None) is False

    assert seen == [] and "TURNSTILE_SECRET_KEY is not set" in caplog.text


def test_why_cloudflare_refused_is_logged_and_the_token_and_secret_never_are(caplog):
    turnstile, _ = verifier(httpx.Response(200, json={"success": False, "error-codes": ["timeout-or-duplicate"]}))

    with caplog.at_level(logging.INFO):
        turnstile.passes("a-secret-looking-token", "203.0.113.5")

    assert "timeout-or-duplicate" in caplog.text
    assert "a-secret-looking-token" not in caplog.text and SECRET not in caplog.text


def test_the_verifier_reports_the_settings_it_lacks():
    assert TurnstileVerifier("", "").missing_config() == ["TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY"]
    assert TurnstileVerifier("secret", "").missing_config() == ["TURNSTILE_SITE_KEY"]
    assert TurnstileVerifier("secret", "site").missing_config() == []
    assert NoCaptcha().missing_config() == []


def test_no_captcha_passes_everyone():
    assert NoCaptcha().passes(None, None) is True and NoCaptcha.from_settings().passes("x", "1.2.3.4") is True


def test_with_the_switch_off_the_gate_passes_everyone_and_asks_nobody(settings):
    from support.captcha import FakeVerifier

    settings.CAPTCHA_VERIFIER = "support.captcha.FakeVerifier"
    FakeVerifier.asked.clear()

    CaptchaGate().check(None, "203.0.113.5")
    CaptchaGate().check("anything", "203.0.113.5")

    assert FakeVerifier.asked == [] and not AuthEvent.objects.exists()


def test_with_the_switch_on_the_gate_refuses_a_visitor_who_did_not_pass_and_records_it(captcha_on):
    with pytest.raises(CaptchaFailed) as refused:
        CaptchaGate().check("bad-token", "203.0.113.5")

    assert refused.value.status_code == 400 and refused.value.get_codes() == "captcha_failed"
    event = AuthEvent.objects.get()
    assert (event.kind, event.ip, event.email_domain) == ("captcha_failed", "203.0.113.5", "")


def test_a_missing_token_is_refused_the_same_way(captcha_on):
    with pytest.raises(CaptchaFailed):
        CaptchaGate().check(None, "203.0.113.5")


def test_a_visitor_who_passes_gets_through_and_nothing_is_recorded(captcha_on):
    CaptchaGate().check("good-token", "203.0.113.5")

    assert not AuthEvent.objects.exists()


def test_the_switch_is_read_on_every_call(captcha_on):
    with pytest.raises(CaptchaFailed):
        CaptchaGate().check("bad-token", None)

    AuthSettings.objects.filter(pk=1).update(captcha_enabled=False)  # staff switch it off in the console
    CaptchaGate().check("bad-token", None)  # at once, no restart

    AuthSettings.objects.filter(pk=1).update(captcha_enabled=True)
    with pytest.raises(CaptchaFailed):
        CaptchaGate().check("bad-token", None)


def test_the_public_config_gives_the_site_key_only_when_the_challenge_is_on(settings, captcha_on):
    assert CaptchaGate().public_config() == {"enabled": True, "site_key": "site-key-for-the-widget"}

    AuthSettings.objects.filter(pk=1).update(captcha_enabled=False)
    assert CaptchaGate().public_config() == {"enabled": False, "site_key": ""}

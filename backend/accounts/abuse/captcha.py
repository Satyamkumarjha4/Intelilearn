"""The sign-up challenge (plan D14, T-captcha): off by default, switched on from the console when abuse shows up.

`CaptchaVerifier` is the port: `passes(token, ip)` says whether a visitor passed. `NoCaptcha` always says yes (the null
object, used when the switch is off); `TurnstileVerifier` asks Cloudflare's Siteverify. `CaptchaGate` is what the
views call: with the switch off it does nothing, and with it on it refuses a missing or failed challenge **before**
anything is sent or kept. The secret key stays in the environment; the switch is a console setting (`AuthSettings`,
audited).

Cloudflare's documentation (read for phase 11.4): `POST https://challenges.cloudflare.com/turnstile/v0/siteverify`,
form or JSON, `secret` and `response` required and `remoteip` optional; a token is at most 2048 characters, lives 300
seconds and is single use; the answer is `{success, error-codes, challenge_ts, hostname, ...}`; its error codes are
`missing-input-secret`, `invalid-input-secret`, `missing-input-response`, `invalid-input-response`, `bad-request`,
`timeout-or-duplicate` and `internal-error`. Any answer that is not a clear `success: true` is a refusal: the gate
fails closed."""

import logging
from abc import ABC, abstractmethod

import httpx
from django.conf import settings
from django.utils.module_loading import import_string
from rest_framework import status
from rest_framework.exceptions import APIException

from ..models import AuthEvent, AuthSettings
from .events import AuthEvents

logger = logging.getLogger(__name__)


class CaptchaFailed(APIException):
    """The challenge was missing or not passed. One answer for both, so it says nothing about why."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "captcha_failed"
    default_detail = "Please complete the check and try again."


class CaptchaVerifier(ABC):
    @abstractmethod
    def passes(self, token: str | None, ip: str | None) -> bool:
        """True only when the visitor clearly passed."""

    @classmethod
    @abstractmethod
    def from_settings(cls) -> "CaptchaVerifier": ...

    def missing_config(self) -> list[str]:
        """The names of the settings this verifier needs and does not have."""
        return []


class NoCaptcha(CaptchaVerifier):
    """No challenge: everyone passes."""

    def passes(self, token: str | None, ip: str | None) -> bool:
        return True

    @classmethod
    def from_settings(cls) -> "NoCaptcha":
        return cls()


class TurnstileVerifier(CaptchaVerifier):
    SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    MAX_TOKEN_LENGTH = 2048  # Cloudflare's own limit
    TIMEOUT_S = 10

    def __init__(self, secret: str, site_key: str = "", http: httpx.Client | None = None):
        self.secret, self.site_key, self._http = secret, site_key, http

    @classmethod
    def from_settings(cls) -> "TurnstileVerifier":
        return cls(settings.TURNSTILE_SECRET_KEY, settings.TURNSTILE_SITE_KEY)

    def missing_config(self) -> list[str]:
        return [
            name
            for name, value in (("TURNSTILE_SITE_KEY", self.site_key), ("TURNSTILE_SECRET_KEY", self.secret))
            if not value
        ]

    def passes(self, token: str | None, ip: str | None) -> bool:
        if not token or not isinstance(token, str) or len(token) > self.MAX_TOKEN_LENGTH:
            return False  # nothing worth asking Cloudflare about
        if not self.secret:
            logger.error("The sign-up challenge is on but TURNSTILE_SECRET_KEY is not set: refusing every visitor")
            return False
        data = {"secret": self.secret, "response": token}
        if ip:
            data["remoteip"] = ip
        try:
            if self._http is not None:
                response = self._http.post(self.SITEVERIFY_URL, data=data)
            else:
                with httpx.Client(timeout=self.TIMEOUT_S) as http:
                    response = http.post(self.SITEVERIFY_URL, data=data)
            if response.status_code != 200:
                logger.warning("Turnstile answered %s", response.status_code)
                return False
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Turnstile could not be asked: %s", type(error).__name__)
            return False
        if not isinstance(body, dict):
            return False  # an answer that is not an object is not an answer
        if body.get("success") is not True:
            codes = body.get("error-codes")
            logger.info(
                "Turnstile refused a visitor: %s",
                ",".join(str(c) for c in codes[:4]) if isinstance(codes, list) else "",
            )
            return False
        return True


class CaptchaGate:
    """Asks the verifier the switch names. The switch is read on every call, so turning it on or off in the console
    takes effect at once."""

    def __init__(self, events: AuthEvents | None = None):
        self.events = events or AuthEvents()

    @staticmethod
    def enabled() -> bool:
        return AuthSettings.load().captcha_enabled

    @staticmethod
    def verifier() -> CaptchaVerifier:
        return import_string(settings.CAPTCHA_VERIFIER).from_settings()

    def public_config(self) -> dict:
        """What the screens need: whether to show the widget, and its public site key (never the secret). The console
        refuses to switch the challenge on without its keys, so a screen that is told "on" has a key to draw it with."""
        on = self.enabled()
        return {"enabled": on, "site_key": settings.TURNSTILE_SITE_KEY if on else ""}

    def check(self, token: str | None, ip: str | None) -> None:
        """Raises `CaptchaFailed` when the challenge is on and the visitor did not clearly pass it."""
        if not self.enabled():
            return
        if not self.verifier().passes(token, ip):
            self.events.record(AuthEvent.Kind.CAPTCHA_FAILED, ip)
            raise CaptchaFailed()

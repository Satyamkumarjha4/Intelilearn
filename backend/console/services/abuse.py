"""The abuse board and the sign-up challenge's switch (plan 10, D14).

`AbuseBoard.report` is read-only: accounts made, codes sent, wrong codes, refused throwaway addresses and failed
challenges per day, the busiest addresses and email domains of the last 24 hours, how many emails are locked and
how many sign-ups are waiting. `ChallengeSwitch` changes the one setting staff have here: whether visitors must
pass Cloudflare Turnstile to sign up or ask for a code. It is audited, and it refuses to switch on without the
keys (a challenge nobody can pass would lock every new person out)."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException

from accounts.abuse.captcha import CaptchaGate
from accounts.abuse.counters import AbuseCounters
from accounts.models import AuthSettings, PendingSignup
from console.audit import AuditTrail


class ChallengeNotConfigured(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "captcha_not_configured"
    default_detail = (
        "Set TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY in the environment before switching the challenge on."
    )


class AbuseBoard:
    DAYS = 14

    def __init__(self, counters: AbuseCounters | None = None):
        self.counters = counters or AbuseCounters()

    def report(self) -> dict:
        return {
            "days": [row.as_dict() for row in self.counters.daily(self.DAYS)],
            "top_addresses": [t.as_dict() for t in self.counters.top_addresses(24)],
            "top_domains": [t.as_dict() for t in self.counters.top_domains(24)],
            "locked_emails": self.counters.locked_emails(),
            "waiting_signups": PendingSignup.objects.filter(expires_at__gt=timezone.now()).count(),
            "challenge": ChallengeSwitch.state(),
        }


class ChallengeSwitch:
    def __init__(self, trail: AuditTrail):
        self.trail = trail

    @staticmethod
    def state() -> dict:
        verifier = CaptchaGate.verifier()
        missing = verifier.missing_config()
        return {
            "captcha_enabled": AuthSettings.load().captcha_enabled,
            "configured": not missing,
            "missing": missing,  # names of settings, never values
            "provider": "Cloudflare Turnstile" if settings.TURNSTILE_SITE_KEY or settings.TURNSTILE_SECRET_KEY else "",
        }

    def set(self, enabled: bool) -> dict:
        """Switch the challenge on or off. No change, no entry in the change log."""
        with transaction.atomic():
            current = AuthSettings.objects.select_for_update().get_or_create(pk=1)[0]
            if current.captcha_enabled == enabled:
                return self.state()
            if enabled and CaptchaGate.verifier().missing_config():
                raise ChallengeNotConfigured()
            before = {"captcha_enabled": current.captcha_enabled}
            current.captcha_enabled = enabled
            current.save(update_fields=["captcha_enabled", "updated_at"])
            self.trail.record(
                "auth_settings.update", "auth_settings", 1, before=before, after={"captcha_enabled": enabled}
            )
        return self.state()

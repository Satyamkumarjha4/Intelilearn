"""Rate limits for the auth endpoints.

Browser traffic reaches Django through the Next.js /api proxy, so REMOTE_ADDR is the frontend container for
everyone. The client address therefore comes from the X-Forwarded-For entry appended by that proxy
(REST_FRAMEWORK["NUM_PROXIES"]). Login is additionally limited per account, so guessing one user's
password is slow no matter how many addresses it comes from.
"""

from rest_framework.exceptions import Throttled
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from .emailrules.canonical import EmailCanonicalizer, MalformedEmail


class AuthRateThrottle(ScopedRateThrottle):
    """Per client address; scope set on the view (auth, auth_refresh)."""


class LoginAccountThrottle(SimpleRateThrottle):
    scope = "auth_account"

    def get_cache_key(self, request, view):
        email = request.data.get("email") if hasattr(request, "data") else None
        if not isinstance(email, str) or not email.strip():
            return None  # nothing to key on; the per-address throttle still applies
        return self.cache_format % {"scope": self.scope, "ident": CanonicalKey.of(email)}


class CanonicalKey:
    """The throttle key for an email: its canonical form, so `a+1@x.com` and `a@x.com` share a budget (plan T8). An
    address that cannot be canonicalised keys on its lowercase text: a limit must exist for it too."""

    @staticmethod
    def of(email: str) -> str:
        try:
            return EmailCanonicalizer.of(email)
        except MalformedEmail:
            return email.strip().lower()


class _CodeThrottle(SimpleRateThrottle):
    """A limit on sending or checking codes. `CodeLimits` runs it after the request is understood, with the email the
    view put on itself, so a request that fails validation spends none of it. The key is the input, never an account."""

    def allow_request(self, request, view):
        self.view_email = getattr(view, "throttle_email", None)
        return super().allow_request(request, view)


class _PerEmail(_CodeThrottle):
    def get_cache_key(self, request, view):
        if not self.view_email:
            return None
        return self.cache_format % {"scope": self.scope, "ident": CanonicalKey.of(self.view_email)}


class _PerAddress(_CodeThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class CodeCooldownThrottle(_PerEmail):
    scope = "auth_code_cooldown"


class CodeSendEmailThrottle(_PerEmail):
    scope = "auth_code_send_email"


class CodeSendAddressThrottle(_PerAddress):
    scope = "auth_code_send_ip"


class CodeCheckEmailThrottle(_PerEmail):
    scope = "auth_code_check_email"


class CodeCheckAddressThrottle(_PerAddress):
    scope = "auth_code_check_ip"


class CodeLimits:
    """The limits on mailing codes and on checking them (plan 8.5). `enforce` raises `Throttled` (a 429 with
    `Retry-After`) for the first one that is used up."""

    SEND = (CodeCooldownThrottle, CodeSendEmailThrottle, CodeSendAddressThrottle)
    CHECK = (CodeCheckEmailThrottle, CodeCheckAddressThrottle)

    def enforce(self, request, view, email: str, group) -> None:
        view.throttle_email = email
        for throttle_class in group:
            throttle = throttle_class()
            if not throttle.allow_request(request, view):
                raise Throttled(wait=throttle.wait())

    def allows(self, request, view, email: str, group) -> bool:
        """Like `enforce`, as a yes or no (a login that cannot send a code still answers the same)."""
        try:
            self.enforce(request, view, email, group)
        except Throttled:
            return False
        return True

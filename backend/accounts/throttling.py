"""Rate limits for the auth endpoints.

Browser traffic reaches Django through the Next.js /api proxy, so REMOTE_ADDR is the frontend container for
everyone. The client address therefore comes from the X-Forwarded-For entry appended by that proxy
(REST_FRAMEWORK["NUM_PROXIES"]). Login is additionally limited per account, so guessing one user's
password is slow no matter how many addresses it comes from.
"""

from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle


class AuthRateThrottle(ScopedRateThrottle):
    """Per client address; scope set on the view (auth, auth_refresh)."""


class LoginAccountThrottle(SimpleRateThrottle):
    scope = "auth_account"

    def get_cache_key(self, request, view):
        email = request.data.get("email") if hasattr(request, "data") else None
        if not isinstance(email, str) or not email.strip():
            return None  # nothing to key on; the per-address throttle still applies
        return self.cache_format % {"scope": self.scope, "ident": email.strip().lower()}

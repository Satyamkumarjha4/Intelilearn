"""Auth cookies. Tokens never reach JavaScript: they live in httpOnly cookies set by the API.

lc_access     access JWT, sent on every request                      path=/
lc_refresh    refresh JWT, only sent to the auth endpoints            path=/api/auth
lc_session    "signed in" marker for the Next.js route guard          path=/  (lifetime of the refresh token)
lc_onboarded  "profile complete" marker for the Next.js route guard   path=/
lc_oauth      state, nonce and PKCE verifier of a sign-in with a provider (signed)   path=/api/auth/oauth  (10 minutes)
lc_finish     a verified provider identity waiting for the "one last step" (signed)  path=/api/auth/oauth  (15 minutes)
lc_signup     the signup ticket: the signed id of this browser's pending sign-up   path=/api/auth  (24 hours)

The markers carry no authority; the API checks the tokens on every request.
"""

from datetime import timedelta

from django.conf import settings


class AuthCookies:
    ACCESS = "lc_access"
    REFRESH = "lc_refresh"
    SESSION = "lc_session"
    ONBOARDED = "lc_onboarded"
    SIGNUP = "lc_signup"
    OAUTH = "lc_oauth"
    FINISH = "lc_finish"
    REFRESH_PATH = "/api/auth"
    OAUTH_PATH = "/api/auth/oauth"

    def __init__(
        self,
        *,
        secure: bool | None = None,
        access_lifetime: timedelta | None = None,
        refresh_lifetime: timedelta | None = None,
    ):
        # Defaults are read from settings at call time, so per-test settings overrides apply.
        self._secure, self._access_lifetime, self._refresh_lifetime = secure, access_lifetime, refresh_lifetime

    def set_session(self, response, *, access: str, refresh: str, onboarded: bool) -> None:
        self._set(response, self.ACCESS, access, self.access_lifetime)
        self._set(response, self.REFRESH, refresh, self.refresh_lifetime, path=self.REFRESH_PATH)
        self._set(response, self.SESSION, "1", self.refresh_lifetime)
        self.set_onboarded(response, onboarded)

    def set_onboarded(self, response, onboarded: bool) -> None:
        if onboarded:
            self._set(response, self.ONBOARDED, "1", self.refresh_lifetime)
        else:
            response.delete_cookie(self.ONBOARDED, path="/", samesite="Lax")

    def set_signup_ticket(self, response, ticket: str, lifetime: timedelta) -> None:
        """The ticket that binds a pending sign-up to this browser (`SignupTicket`). It carries no authority."""
        self._set(response, self.SIGNUP, ticket, lifetime, path=self.REFRESH_PATH)

    def set_oauth(self, response, value: str, max_age: int) -> None:
        self._set(response, self.OAUTH, value, timedelta(seconds=max_age), path=self.OAUTH_PATH)

    def clear_oauth(self, response) -> None:
        response.delete_cookie(self.OAUTH, path=self.OAUTH_PATH, samesite="Lax")

    def set_finish(self, response, value: str, max_age: int) -> None:
        self._set(response, self.FINISH, value, timedelta(seconds=max_age), path=self.OAUTH_PATH)

    def clear_finish(self, response) -> None:
        response.delete_cookie(self.FINISH, path=self.OAUTH_PATH, samesite="Lax")

    def clear_signup_ticket(self, response) -> None:
        response.delete_cookie(self.SIGNUP, path=self.REFRESH_PATH, samesite="Lax")

    def clear(self, response) -> None:
        for name in (self.ACCESS, self.SESSION, self.ONBOARDED):
            response.delete_cookie(name, path="/", samesite="Lax")
        response.delete_cookie(self.REFRESH, path=self.REFRESH_PATH, samesite="Lax")

    @property
    def access_lifetime(self) -> timedelta:
        return self._access_lifetime or settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]

    @property
    def refresh_lifetime(self) -> timedelta:
        return self._refresh_lifetime or settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]

    @property
    def secure(self) -> bool:
        return self._secure if self._secure is not None else settings.AUTH_COOKIE_SECURE

    def _set(self, response, name: str, value: str, max_age: timedelta, path: str = "/") -> None:
        response.set_cookie(
            name,
            value,
            max_age=int(max_age.total_seconds()),
            path=path,
            httponly=True,
            secure=self.secure,
            samesite="Lax",
        )

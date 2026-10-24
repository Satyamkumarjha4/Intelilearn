"""Auth cookies. Tokens never reach JavaScript: they live in httpOnly cookies set by the API.

lc_access     access JWT, sent on every request                      path=/
lc_refresh    refresh JWT, only sent to the auth endpoints            path=/api/auth
lc_session    "signed in" marker for the Next.js route guard          path=/  (lifetime of the refresh token)
lc_onboarded  "profile complete" marker for the Next.js route guard   path=/

The markers carry no authority; the API checks the tokens on every request.
"""

from django.conf import settings

ACCESS_COOKIE = "lc_access"
REFRESH_COOKIE = "lc_refresh"
SESSION_COOKIE = "lc_session"
ONBOARDED_COOKIE = "lc_onboarded"
REFRESH_COOKIE_PATH = "/api/auth"


def _set(response, name, value, max_age, path="/"):
    response.set_cookie(
        name,
        value,
        max_age=int(max_age.total_seconds()),
        path=path,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="Lax",
    )


def set_auth_cookies(response, *, access: str, refresh: str, onboarded: bool) -> None:
    jwt = settings.SIMPLE_JWT
    _set(response, ACCESS_COOKIE, access, jwt["ACCESS_TOKEN_LIFETIME"])
    _set(response, REFRESH_COOKIE, refresh, jwt["REFRESH_TOKEN_LIFETIME"], path=REFRESH_COOKIE_PATH)
    _set(response, SESSION_COOKIE, "1", jwt["REFRESH_TOKEN_LIFETIME"])
    set_onboarded_cookie(response, onboarded)


def set_onboarded_cookie(response, onboarded: bool) -> None:
    if onboarded:
        _set(response, ONBOARDED_COOKIE, "1", settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"])
    else:
        response.delete_cookie(ONBOARDED_COOKIE, path="/", samesite="Lax")


def clear_auth_cookies(response) -> None:
    for name in (ACCESS_COOKIE, SESSION_COOKIE, ONBOARDED_COOKIE):
        response.delete_cookie(name, path="/", samesite="Lax")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, samesite="Lax")

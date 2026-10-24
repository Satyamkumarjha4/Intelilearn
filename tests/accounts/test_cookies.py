"""Unit under test: `accounts.cookies.AuthCookies`, which sets and clears the auth cookies on API responses.

Why: the tokens must stay out of JavaScript's reach (httpOnly), the refresh token must only travel to the auth
endpoints, and sign-out must remove every cookie on the path it was set on, or a stale session survives.

Use cases:
- a session sets the access, refresh and session cookies with their lifetimes, httpOnly and SameSite=Lax
- the refresh cookie is scoped to /api/auth
- the onboarded marker is set when the profile is complete and deleted otherwise
- clearing removes every cookie on the path it was set on
- Secure follows the setting (or the injected value)
"""

from datetime import timedelta

from django.http import HttpResponse

from accounts.cookies import AuthCookies


def cookies(**kwargs):
    return AuthCookies(access_lifetime=timedelta(minutes=30), refresh_lifetime=timedelta(days=7), **kwargs)


def test_session_sets_the_three_cookies_httponly_and_lax():
    response = HttpResponse()

    cookies().set_session(response, access="a", refresh="r", onboarded=False)

    access, refresh, session = (
        response.cookies[n] for n in (AuthCookies.ACCESS, AuthCookies.REFRESH, AuthCookies.SESSION)
    )
    assert (access.value, access["max-age"], access["path"]) == ("a", 1800, "/")
    assert (session.value, session["max-age"]) == ("1", 7 * 86400)
    assert all(c["httponly"] and c["samesite"] == "Lax" for c in (access, refresh, session))


def test_refresh_cookie_is_scoped_to_the_auth_endpoints():
    response = HttpResponse()

    cookies().set_session(response, access="a", refresh="r", onboarded=False)

    assert response.cookies[AuthCookies.REFRESH]["path"] == "/api/auth"


def test_onboarded_marker_follows_the_profile():
    complete, incomplete = HttpResponse(), HttpResponse()

    cookies().set_onboarded(complete, True)
    cookies().set_onboarded(incomplete, False)

    assert complete.cookies[AuthCookies.ONBOARDED].value == "1"
    assert incomplete.cookies[AuthCookies.ONBOARDED]["max-age"] == 0  # a deletion


def test_clear_removes_every_cookie_on_its_path():
    response = HttpResponse()

    cookies().clear(response)

    paths = {name: response.cookies[name]["path"] for name in response.cookies}
    assert paths == {AuthCookies.ACCESS: "/", AuthCookies.SESSION: "/", AuthCookies.ONBOARDED: "/",
                     AuthCookies.REFRESH: "/api/auth"}  # fmt: skip
    assert all(response.cookies[name]["max-age"] == 0 for name in response.cookies)


def test_secure_follows_the_setting(settings):
    settings.AUTH_COOKIE_SECURE = True
    from_setting, injected = HttpResponse(), HttpResponse()

    cookies().set_session(from_setting, access="a", refresh="r", onboarded=True)
    cookies(secure=False).set_session(injected, access="a", refresh="r", onboarded=True)

    assert from_setting.cookies[AuthCookies.ACCESS]["secure"] is True
    assert not injected.cookies[AuthCookies.ACCESS]["secure"]

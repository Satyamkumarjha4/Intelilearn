"""Unit under test: the whole API's URL table (`config/urls.py` and every app's `urls.py`), walked as a whole.

Why: each app tests that its own endpoints refuse a signed-out caller, but a new view that forgets its permission
class, or sets `permission_classes = []`, is open to the world and no per-app test would notice. DRF's default is
"signed in only", so an endpoint is open only when someone wrote that down. This guard lists every route that is open on
purpose and fails for any other that is, and for any listed one that no longer is, so the allow-list stays the truth.

Use cases:
- the routes open without a sign-in are exactly the short list below (health, the CSRF cookie, register, sign-in,
  refresh and sign-out, the profile choice lists, a signed media URL, the payment webhook, the two public landing
  endpoints, and the API's own schema and docs), each with its reason
- every other route refuses a signed-out request, whatever its method (401, 403, or the console's 404 for "no such
  page"), and nothing it does is reached
- the walk really found the API (a table that moved or an empty walk would pass for nothing)
"""

import re

import pytest
from django.urls import URLResolver, get_resolver

pytestmark = pytest.mark.django_db

# The routes that are open on purpose, with the reason. A new entry is a decision made in review.
OPEN = {
    "api/health": "uptime checks and the stack's own readiness check",
    "api/auth/csrf": "sets the CSRF cookie before anyone has signed in",
    "api/auth/register": "makes an account",
    "api/auth/login": "signs in",
    "api/auth/refresh": "renews a session from its own refresh cookie, which is the credential",
    "api/auth/logout": "signs out, harmlessly, for anyone",
    "api/profile/options": "the choice lists the sign-up screens read before there is an account",
    "api/media/<str:asset_id>": "a lesson's image: the URL's signature is the credential (an iframe sends no cookie)",
    "api/payments/webhooks/<str:gateway>": "the payment provider calls it; the signature is the credential",
    "api/public/testimonials": "the landing page, shown to visitors",
    "api/public/pricing": "the landing page, shown to visitors",
    "api/schema": "the OpenAPI schema",
    "api/docs": "Swagger",
    "api/redoc": "ReDoc",
}
SAMPLES = {"uuid": "00000000-0000-4000-8000-000000000000", "int": "1", "str": "x", "slug": "x", "path": "x"}
SAFE_TO_SKIP = {"options", "head"}


class ApiRoutes:
    """Every `api/...` route of the project with the view class behind it."""

    @classmethod
    def all(cls) -> list[tuple[str, type, list[str]]]:
        return list(cls._walk(get_resolver().url_patterns, ""))

    @classmethod
    def _walk(cls, patterns, prefix):
        for pattern in patterns:
            route = prefix + str(pattern.pattern)
            if isinstance(pattern, URLResolver):
                yield from cls._walk(pattern.url_patterns, route)
                continue
            if not route.startswith("api/"):
                continue  # the Django admin has its own login
            view = getattr(pattern.callback, "cls", None) or getattr(pattern.callback, "view_class", None)
            assert view is not None, f"{route} is not a class-based view: this guard cannot see its permissions"
            actions = getattr(pattern.callback, "actions", None)
            methods = list(actions) if actions else [m for m in view.http_method_names if hasattr(view, m)]
            yield route, view, [m for m in methods if m not in SAFE_TO_SKIP]

    @staticmethod
    def url(route: str) -> str:
        return "/" + re.sub(r"<(?:(\w+):)?\w+>", lambda m: SAMPLES.get(m.group(1) or "str", "x"), route)

    @staticmethod
    def is_open(view) -> bool:
        classes = [c.__name__ for c in view.permission_classes]
        return not classes or "AllowAny" in classes


def test_the_routes_open_without_a_sign_in_are_exactly_the_listed_ones():
    open_routes = {route for route, view, _ in ApiRoutes.all() if ApiRoutes.is_open(view)}

    unlisted, stale = sorted(open_routes - set(OPEN)), sorted(set(OPEN) - open_routes)
    assert open_routes == set(OPEN), f"open but not listed: {unlisted}; listed but no longer open: {stale}"


def test_every_other_route_refuses_a_signed_out_request_whatever_its_method(api_client):
    checked, accepted = 0, []
    for route, _view, methods in ApiRoutes.all():
        if route in OPEN:
            continue
        for method in methods:
            response = getattr(api_client, method)(ApiRoutes.url(route), {}, format="json")
            checked += 1
            if response.status_code not in (401, 403, 404):
                accepted.append(f"{method.upper()} /{route} -> {response.status_code}")

    assert checked > 80
    assert accepted == [], "a signed-out request got further than a refusal"


def test_the_walk_found_the_api():
    routes = ApiRoutes.all()

    assert len(routes) > 80
    assert {"api/lessons", "api/credits/wallet", "api/console/overview"} <= {route for route, _, _ in routes}
    assert all(methods for _, _, methods in routes)

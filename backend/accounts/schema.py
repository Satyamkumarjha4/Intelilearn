from drf_spectacular.extensions import OpenApiAuthenticationExtension

from .cookies import AuthCookies


class CookieJWTScheme(OpenApiAuthenticationExtension):
    """Documents cookie auth in Swagger. Log in via POST /api/auth/login in the same browser and
    the cookie is sent automatically; Swagger UI adds the CSRF header itself."""

    target_class = "accounts.authentication.CookieJWTAuthentication"
    name = "cookieAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "cookie", "name": AuthCookies.ACCESS}

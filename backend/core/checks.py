from django.conf import settings
from django.core.checks import Error, Tags, register


class DeploySecurityChecks:
    """`check --deploy` errors for settings that must never reach a deployment."""

    def __init__(
        self,
        secret_key: str | None = None,
        dev_secret_key: str | None = None,
        debug: bool | None = None,
        proxy_count_explicit: bool | None = None,
    ):
        self._secret_key, self._dev_secret_key = secret_key, dev_secret_key
        self._debug, self._proxy_count_explicit = debug, proxy_count_explicit

    def errors(self) -> list[Error]:
        return [*self.secret_key(), *self.proxy_count()]

    def secret_key(self) -> list[Error]:
        """Never run a deployment with the development SECRET_KEY (it also signs the JWTs)."""
        secret = self._secret_key if self._secret_key is not None else settings.SECRET_KEY
        dev = self._dev_secret_key if self._dev_secret_key is not None else settings.DEV_SECRET_KEY
        if secret != dev:
            return []
        return [
            Error(
                "DJANGO_SECRET_KEY is not set; the built-in development key is in use.",
                hint="Set DJANGO_SECRET_KEY to a long random value in .env.",
                id="core.E001",
            )
        ]

    def proxy_count(self) -> list[Error]:
        """A deployment says how many proxies stand in front of Django (`TRUSTED_PROXY_COUNT`), or the per-address
        limits
        count the wrong address: the development default of 1 is right for the Next proxy alone, and wrong behind
        an edge."""
        debug = self._debug if self._debug is not None else settings.DEBUG
        explicit = (
            self._proxy_count_explicit
            if self._proxy_count_explicit is not None
            else settings.TRUSTED_PROXY_COUNT_EXPLICIT
        )
        if debug or explicit:
            return []
        return [
            Error(
                "TRUSTED_PROXY_COUNT is not set, so the client address behind the proxies is a guess.",
                hint="Set TRUSTED_PROXY_COUNT to the number of proxies in front of Django "
                "(the Next.js /api proxy counts as "
                "one) and EDGE_PROXY_HOPS on the frontend to the proxies in front of Next. The edge must overwrite "
                "X-Forwarded-For or append to it (docs/reference/api.md).",
                id="core.E002",
            )
        ]


@register(Tags.security, deploy=True)
def secret_key_check(app_configs=None, **kwargs):
    return DeploySecurityChecks().secret_key()


@register(Tags.security, deploy=True)
def trusted_proxy_check(app_configs=None, **kwargs):
    return DeploySecurityChecks().proxy_count()

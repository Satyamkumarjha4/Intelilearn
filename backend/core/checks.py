from django.conf import settings
from django.core.checks import Error, Tags, register


class DeploySecurityChecks:
    """`check --deploy` errors for settings that must never reach a deployment."""

    def __init__(self, secret_key: str | None = None, dev_secret_key: str | None = None):
        self._secret_key, self._dev_secret_key = secret_key, dev_secret_key

    def errors(self) -> list[Error]:
        return self.secret_key()

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


@register(Tags.security, deploy=True)
def secret_key_check(app_configs=None, **kwargs):
    return DeploySecurityChecks().errors()

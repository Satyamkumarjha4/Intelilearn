from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def secret_key_check(app_configs=None, **kwargs):
    """`check --deploy`: never run a deployment with the development SECRET_KEY (it also signs the JWTs)."""
    if settings.SECRET_KEY == settings.DEV_SECRET_KEY:
        return [
            Error(
                "DJANGO_SECRET_KEY is not set; the built-in development key is in use.",
                hint="Set DJANGO_SECRET_KEY to a long random value in .env.",
                id="core.E001",
            )
        ]
    return []

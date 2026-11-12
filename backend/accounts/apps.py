from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        from . import (  # noqa: F401  (signal handlers, the OpenAPI auth extension, mail backends and checks)
            mail,
            schema,
            signals,
        )

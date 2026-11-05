from django.apps import AppConfig


class CreditsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "credits"

    def ready(self):
        from . import signals  # noqa: F401  (the signup grant on account_ready)

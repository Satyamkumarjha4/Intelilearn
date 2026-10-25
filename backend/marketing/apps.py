from django.apps import AppConfig


class MarketingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "marketing"

    def ready(self):
        from . import signals  # noqa: F401  (clear the picker's cached ids when a question changes)

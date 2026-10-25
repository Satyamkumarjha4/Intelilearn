from django.apps import AppConfig


class LessonsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lessons"

    def ready(self):
        from . import signals  # noqa: F401  (delete media files with their rows)

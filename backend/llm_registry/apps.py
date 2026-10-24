from django.apps import AppConfig


class LlmRegistryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "llm_registry"
    verbose_name = "LLM model registry"

    def ready(self):
        from . import checks, signals  # noqa: F401  (register system checks and cache/node-config signals)

import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandError

from llm_registry.models import NodeModelBinding
from llm_registry.seed import default_registry
from llm_registry.serialization import import_registry


class Command(BaseCommand):
    help = "Load the default model registry, or a registry JSON file exported with export_registry."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, help="Registry JSON to import instead of the defaults.")
        parser.add_argument(
            "--force", action="store_true", help="Apply the defaults even if bindings already exist (overwrites them)."
        )

    def handle(self, *args, file=None, force=False, **options):
        if file:
            data = json.loads(file.read_text())
        else:
            if NodeModelBinding.objects.exists() and not force:
                self.stdout.write("Registry already has bindings; leaving it alone (use --force to reset to defaults).")
                return
            data = default_registry()

        try:
            counts = import_registry(data)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        summary = ", ".join(f"{n} {name}" for name, n in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Registry loaded: {summary}"))

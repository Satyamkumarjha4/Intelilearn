import json
from pathlib import Path

from django.core.management import BaseCommand

from llm_registry.serialization import export_registry


class Command(BaseCommand):
    help = "Write the model registry as JSON (stdout, or --output file). Load it elsewhere with seed_registry --file."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path)

    def handle(self, *args, output=None, **options):
        text = json.dumps(export_registry(), indent=2)
        if output:
            output.write_text(text + "\n")
            self.stdout.write(self.style.SUCCESS(f"Registry written to {output}"))
        else:
            self.stdout.write(text)

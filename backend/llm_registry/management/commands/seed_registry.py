import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandError

from llm_registry.models import NodeModelBinding
from llm_registry.seed import SEED_PROFILES
from llm_registry.serialization import RegistrySerializer


class Command(BaseCommand):
    help = "Load a default model registry profile, or a registry JSON file exported with export_registry."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, help="Registry JSON to import instead of the defaults.")
        parser.add_argument(
            "--profile",
            default="default",
            help=f"Which defaults to load: {', '.join(SEED_PROFILES)}. 'cheap' uses only the cheapest models at low "
            "reasoning effort, to validate the flow without hitting rate or billing limits.",
        )
        parser.add_argument(
            "--force", action="store_true", help="Apply the defaults even if bindings already exist (overwrites them)."
        )

    def fill_unbound(self, data: dict) -> None:
        """An existing registry is left alone, except that a node with no binding (one a release added) is bound."""
        filled = RegistrySerializer().fill_unbound(data)
        if filled["bound"]:
            self.stdout.write(self.style.SUCCESS("Bound " + ", ".join(filled["bound"]) + " from the profile."))
        if filled["skipped"]:
            self.stdout.write(
                self.style.WARNING(
                    "Could not bind "
                    + ", ".join(filled["skipped"])
                    + ": none of the profile's models is on this install. "
                    "Bind a model in the admin."
                )
            )
        if not filled["bound"] and not filled["skipped"]:
            self.stdout.write("Registry already has bindings; leaving it alone (use --force to reset to defaults).")

    def handle(self, *args, file=None, force=False, profile="default", **options):
        if file:
            data = json.loads(file.read_text())
        else:
            if profile not in SEED_PROFILES:
                raise CommandError(f"Unknown profile {profile!r}; choose one of: {', '.join(SEED_PROFILES)}")
            data = SEED_PROFILES[profile]().build()
            if NodeModelBinding.objects.exists() and not force:
                self.fill_unbound(data)
                return

        try:
            counts = RegistrySerializer().load(data)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        summary = ", ".join(f"{n} {name}" for name, n in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Registry loaded: {summary}"))

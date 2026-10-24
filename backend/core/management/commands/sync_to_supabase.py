from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command

from core.sync import DatabaseSyncer


class Command(BaseCommand):
    help = "Migrate both databases, then copy local docker-Postgres rows that Supabase doesn't have (insert-only)."

    def handle(self, *args, **options):
        if not settings.USING_SUPABASE:
            raise CommandError("SUPABASE_DATABASE_URL is not set; there is nothing to sync to.")

        # Both schemas must match the current models before rows can move between them.
        call_command("migrate", database="local", interactive=False, verbosity=0)
        call_command("migrate", database="default", interactive=False, verbosity=0)

        report = DatabaseSyncer(source="local", target="default").sync()
        for label, result in report.models.items():
            if result.inserted or result.conflicts:
                self.stdout.write(
                    f"  {label}: {result.inserted} inserted, {result.skipped} already present, "
                    f"{result.conflicts} conflicts"
                )
        summary = f"Local → Supabase sync done: {report.inserted} rows copied, {report.conflicts} conflicts"
        self.stdout.write(self.style.SUCCESS(summary))

from django.conf import settings
from django.core.management import BaseCommand, call_command


class Command(BaseCommand):
    help = (
        "Run on backend start: migrate the active database (with Supabase, first sync local data up), "
        "then create the LangGraph checkpoint tables."
    )

    def handle(self, *args, **options):
        if settings.USING_SUPABASE and settings.SYNC_LOCAL_TO_SUPABASE:
            self.stdout.write("Supabase configured: syncing local Postgres → Supabase")
            call_command("sync_to_supabase")  # also migrates both databases
        else:
            target = "Supabase" if settings.USING_SUPABASE else "local Postgres"
            self.stdout.write(f"Migrating {target}")
            call_command("migrate", interactive=False)
        call_command("setup_checkpointer")

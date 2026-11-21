"""`manage.py audit_seed [--only slug ...] [--skip-history]`: the synthetic personas of the pre-launch audit.

Runs only on a throwaway stack (DEBUG on, no Supabase) with AUDIT_PERSONA_PASSWORD set; safe to run again. Prints the
persona names and addresses, never a password (the audit keeps those in a git-ignored file).
"""

from django.core.management.base import BaseCommand, CommandError

from core.audit.errors import SeedFailed
from core.audit.seeder import AuditSeeder, SeedRefused
from core.audit.world import DefaultSeedWorld


class Command(BaseCommand):
    help = "Create the audit's synthetic personas (audit-<name>@example.test). Safe to repeat; throwaway stacks only."

    def add_arguments(self, parser):
        parser.add_argument("--only", nargs="+", metavar="SLUG", help="Only these personas (e.g. weekly history).")
        parser.add_argument("--skip-history", action="store_true", help="Leave out the lesson, quiz and sheet history.")
        parser.add_argument("--history-timeout", type=float, default=300, help="Seconds to wait for the worker.")

    def handle(self, *args, only=None, skip_history=False, history_timeout=300, **options):
        seeder = AuditSeeder(DefaultSeedWorld.build(history_timeout_s=history_timeout))
        try:
            report = seeder.seed(
                only=set(only) if only else None,
                skip={"HaveHistory"} if skip_history else None,
                progress=lambda slug: self.stdout.write(f"  {slug} ..."),
            )
        except (SeedRefused, SeedFailed) as problem:
            raise CommandError(str(problem)) from None
        for result in report.results:
            made = "made" if result.created else "already there"
            self.stdout.write(f"{result.persona.slug:13} {result.persona.email}  ({made}) {result.persona.purpose}")
            for line in result.applied:
                self.stdout.write(f"                {line}")
        self.stdout.write(self.style.SUCCESS(f"{len(report.results)} personas ready. Passwords are not printed."))

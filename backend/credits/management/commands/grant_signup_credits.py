"""`manage.py grant_signup_credits [--dry-run]`: give the 30 signup credits to every active account that does not
have them
(credits plan D10, T30). Run it once before the credit gate is switched on; it is safe to run again."""

from django.core.management.base import BaseCommand

from credits.earning.signup import SignupGrant


class Command(BaseCommand):
    help = "Give the signup credits to accounts that were made before credits existed. Safe to repeat."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Say what would be done and write nothing.")

    def handle(self, *args, dry_run=False, **options):
        report = SignupGrant().backfill(dry_run=dry_run)
        accounts = "account" if report.granted == 1 else "accounts"
        if report.granted == 0:
            self.stdout.write(
                f"Nothing to do: {report.already} already have them, {report.skipped} closed accounts skipped."
            )
        elif dry_run:
            self.stdout.write(
                f"Dry run: would give the signup credits to {report.granted} {accounts} "
                f"({report.already} already have them, {report.skipped} closed accounts skipped)."
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Gave the signup credits to {report.granted} {accounts} "
                    f"({report.already} already had them, {report.skipped} closed accounts skipped)."
                )
            )

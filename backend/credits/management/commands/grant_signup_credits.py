"""`manage.py grant_signup_credits [--dry-run]`: give the 30 signup credits to every active account that does not
have them and whose email is verified (credits plan D10, T30; sign-in plan D9). Run it once before the credit gate is
switched on; it is safe to run again. Accounts whose email was never proved are skipped and counted: they get the
credits the day they prove it."""

from django.core.management.base import BaseCommand

from credits.earning.signup import BackfillReport, SignupGrant


class Command(BaseCommand):
    help = "Give the signup credits to verified accounts that were made before credits existed. Safe to repeat."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Say what would be done and write nothing.")

    def handle(self, *args, dry_run=False, **options):
        report = SignupGrant().backfill(dry_run=dry_run)
        accounts = "account" if report.granted == 1 else "accounts"
        if report.granted == 0:
            self.stdout.write(f"Nothing to do: {self._others(report, 'already have them')}")
        elif dry_run:
            self.stdout.write(
                f"Dry run: would give the signup credits to {report.granted} {accounts} "
                f"({self._others(report, 'already have them')})."
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Gave the signup credits to {report.granted} {accounts} "
                    f"({self._others(report, 'already had them')})."
                )
            )
        if report.unverified:
            self.stdout.write(
                self.style.WARNING(
                    f"{report.unverified} active accounts were skipped because their email was never verified. "
                    "They get the credits when they prove it (a code at sign-in), not before."
                )
            )

    @staticmethod
    def _others(report: BackfillReport, had: str) -> str:
        return (
            f"{report.already} {had}, {report.skipped} closed accounts skipped, {report.unverified} unverified skipped"
        )

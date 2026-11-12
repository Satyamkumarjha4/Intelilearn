from django.core.management import BaseCommand
from django.db import transaction

from accounts.models import User


class Command(BaseCommand):
    help = (
        "Before launch: make accounts whose email was never proved ask for a code at their next password sign-in. "
        "Sets 'legacy' accounts back to unverified. Their credits stay. "
        "Staff accounts are left alone unless --include-staff."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Say what would change and write nothing.")
        parser.add_argument("--keep-staff", action="store_true", help="Leave staff accounts as they are (the default).")
        parser.add_argument("--include-staff", action="store_true", help="Also make staff accounts ask for a code.")

    def handle(self, *args, dry_run=False, include_staff=False, **options):
        accounts = User.objects.filter(
            email_verification_source=User.VerificationSource.LEGACY,
            email_verified_at__isnull=False,
            deleted_at__isnull=True,
        )
        if not include_staff:
            accounts = accounts.filter(is_staff=False, is_superuser=False)
        count = accounts.count()
        if dry_run:
            self.stdout.write(f"Dry run: would make {count} legacy accounts ask for a code at their next sign-in.")
            return
        with transaction.atomic():
            accounts.update(email_verified_at=None, email_verification_source="")
        self.stdout.write(self.style.SUCCESS(f"{count} legacy accounts will ask for a code at their next sign-in."))

"""`manage.py credits_audit [--user ID_OR_EMAIL]`: check that every learner's ledger equals their buckets (credits plan
T4). Prints a line for each break and exits non-zero when there is one, so the hourly job and a deploy step can use
it."""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from credits.audit import LedgerAudit


class Command(BaseCommand):
    help = "Check that each learner's credit ledger adds up to their buckets. Exits non-zero when it does not."

    def add_arguments(self, parser):
        parser.add_argument("--user", help="Check one learner, by id or email (default: everyone with credits).")

    def handle(self, *args, user=None, **options):
        audit = LedgerAudit()
        report = audit.check(self._learner(user)) if user else audit.check_all()
        for found in report.breaks:
            self.stdout.write(
                f"BREAK user {found.user_id}: ledger {found.ledger_sum}, buckets {found.bucket_sum}, "
                f"last balance {found.last_balance}. " + "; ".join(found.problems)
            )
        if report.breaks:
            count = len(report.breaks)
            raise CommandError(f"{count} {'break' if count == 1 else 'breaks'} in {report.checked} learners checked.")
        noun = "learner" if report.checked == 1 else "learners"
        self.stdout.write(self.style.SUCCESS(f"{report.checked} {noun} checked, the books balance."))

    @staticmethod
    def _learner(who: str) -> User:
        found = User.objects.filter(email__iexact=who).first()
        if found is None:
            try:
                found = User.objects.filter(pk=who).first()
            except Exception:  # not a valid id
                found = None
        if found is None:
            raise CommandError(f"No learner {who!r}.")
        return found

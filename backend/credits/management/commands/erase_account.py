"""`manage.py erase_account IDENTIFIER [--dry-run]`: erase one learner's account (credits plan P5). The account is
anonymised in
place and everything the learner made is erased; unspent credits are written off on the ledger. Safe to repeat. Run
it with
--dry-run first."""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from credits.erasure import AccountErasure
from credits.refusals import credits_word


class Command(BaseCommand):
    help = "Erase a learner's account by email or id: anonymise it and erase what they made. Use --dry-run first."

    def add_arguments(self, parser):
        parser.add_argument("who", help="The learner's email or id.")
        parser.add_argument("--dry-run", action="store_true", help="Say what would be done and change nothing.")
        parser.add_argument(
            "--yes", action="store_true", help="Do not ask for the email to be typed (for scripts; there is no undo)."
        )

    def handle(self, *args, who, dry_run=False, yes=False, **options):
        user = self._learner(who)
        erasure = AccountErasure()
        if not dry_run and not yes and user.deleted_at is None:
            self._confirm(user, erasure.erase(user, dry_run=True))
        report = erasure.erase(user, dry_run=dry_run)
        if report.already_erased:
            self.stdout.write(f"Account {user.pk} was already erased. Nothing to do.")
            return
        summary = self._summary(report)
        if dry_run:
            self.stdout.write(f"Dry run: would erase account {user.pk}: {summary}")
        else:
            self.stdout.write(self.style.SUCCESS(f"Erased account {user.pk}: {summary}"))

    @staticmethod
    def _summary(report) -> str:
        return (
            f"{report.lessons} lessons and {report.quizzes} quizzes, {report.released_holds} open reserves released, "
            f"{credits_word(report.forfeited)} forfeited."
        )

    def _confirm(self, user: User, plan) -> None:
        """Show what will happen and ask for the account's email. Nothing is done unless it is typed exactly."""
        self.stdout.write(
            f"This will erase account {user.pk} ({user.email}): {self._summary(plan)} It cannot be undone."
        )
        try:
            typed = input("Type the account's email to go ahead: ")
        except (EOFError, OSError):
            raise CommandError("There is no terminal to ask on. Use --yes to confirm in a script.") from None
        if typed.strip().lower() != user.email.lower():
            raise CommandError("That is not the account's email, so nothing was done.")

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

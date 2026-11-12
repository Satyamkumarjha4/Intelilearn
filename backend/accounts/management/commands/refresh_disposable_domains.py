import httpx
from django.core.management import BaseCommand, CommandError

from accounts.emailrules.snapshot import DisposableSnapshot, SnapshotRefused


class Command(BaseCommand):
    help = (
        "Refresh the vendored list of disposable email domains from the public blocklist (writes "
        "accounts/data/disposable_email_domains.txt with its source commit and date). "
        "Review the diff, run the tests, commit."
    )

    @staticmethod
    def client() -> httpx.Client:
        return httpx.Client(timeout=30, headers={"User-Agent": "socra-disposable-refresh"})

    def handle(self, *args, **options):
        try:
            with self.client() as client:
                result = DisposableSnapshot(client).refresh()
        except SnapshotRefused as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS(f"{result.domains} domains, source commit {result.commit}."))
        if result.removed:
            self.stdout.write(f"Dropped real providers the list held: {', '.join(result.removed)}.")

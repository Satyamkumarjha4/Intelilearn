import httpx
from django.core.management import BaseCommand, CommandError

from core.proxy_probe import ForwardedHeaderProbe


class Command(BaseCommand):
    help = (
        "Send a forged X-Forwarded-For through the front door and print which address Django counted for the "
        "per-address limits. Run it where the app's cache is reachable, against the PUBLIC url after a deploy: "
        "a single forged entry must not be the one counted."
    )

    def add_arguments(self, parser):
        parser.add_argument("--url", default="http://frontend:3000", help="the front door to probe (default: dev)")

    def handle(self, *args, url, **options):
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            report = ForwardedHeaderProbe(client).run(url)
        for finding in report.findings:
            counted = finding.counted or "another address"
            self.stdout.write(
                f"{'ok  ' if finding.passed else 'FAIL'} {finding.name}: sent {finding.header!r}, "
                f"counted {counted}: {finding.meaning}"
            )
        if not report.passed:
            raise CommandError("A client can choose the address the limits count. Fix the edge, then run this again.")
        self.stdout.write("The forged address was not counted.")

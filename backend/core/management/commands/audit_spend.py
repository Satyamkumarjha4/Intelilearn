"""`manage.py audit_spend`: what the live audit has spent on models, and whether it is within `LIVE_MAX_COST_USD`.

Exits with an error when over the cap, so a script can stop before another call.
"""

from django.core.management.base import BaseCommand, CommandError

from core.audit.spend import AuditSpend, BadCap


class Command(BaseCommand):
    help = "Print the model spend of this (throwaway) stack against LIVE_MAX_COST_USD; fail when over."

    def handle(self, *args, **options):
        try:
            report = AuditSpend.from_environment().report()
        except BadCap as problem:
            raise CommandError(str(problem)) from None
        self.stdout.write(
            f"{report.calls} calls, {report.input_tokens} tokens in, {report.output_tokens} out: "
            f"${report.cost_usd:.2f} of ${report.cap:.2f}"
        )
        if report.unpriced:
            self.stdout.write(
                self.style.WARNING(f"{report.unpriced} calls have no price in the log, so the total may be low.")
            )
        if report.over:
            raise CommandError(f"over budget: ${report.cost_usd:.2f} is more than ${report.cap:.2f}.")
        self.stdout.write(self.style.SUCCESS("within budget"))

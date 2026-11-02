from django.core.management import BaseCommand

from lessons.concept_backfill import ConceptIndexBackfill


class Command(BaseCommand):
    help = (
        "Write the concept index of lessons made before it existed, from their stored plan and pages, so a quiz result "
        "can link a weak concept to the page that teaches it. Safe to run again: it fills only empty indexes."
    )

    def __init__(self, *args, backfill: ConceptIndexBackfill | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.backfill = backfill

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Say what would be indexed and write nothing.")

    def handle(self, *args, dry_run=False, **options):
        report = (self.backfill or ConceptIndexBackfill()).run(dry_run=dry_run)
        for line in report.lines():
            self.stdout.write(line)

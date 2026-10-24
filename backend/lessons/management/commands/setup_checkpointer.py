from django.core.management import BaseCommand

from lessons.checkpoints import CheckpointerFactory


class Command(BaseCommand):
    help = "Create the LangGraph checkpoint tables in the active database (safe to repeat)."

    def handle(self, *args, **options):
        CheckpointerFactory().setup()
        self.stdout.write(self.style.SUCCESS("Checkpoint tables are ready."))

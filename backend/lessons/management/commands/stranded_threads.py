from django.core.management import BaseCommand

from lessons.stranded import StrandedThreads


class Command(BaseCommand):
    help = (
        "List lessons whose LangGraph thread waits at, or would resume into, a node that no longer exists in the "
        "current graph (after a release that removed or renamed one). --mark-failed ends them with a message."
    )

    def __init__(self, *args, finder: StrandedThreads | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.finder = finder

    def add_arguments(self, parser):
        parser.add_argument(
            "--mark-failed",
            action="store_true",
            help="Mark each stranded lesson failed, with a message that tells the learner to start a new lesson.",
        )

    def handle(self, *args, mark_failed=False, **options):
        finder = self.finder or StrandedThreads()
        stranded = finder.find()
        if not stranded:
            self.stdout.write("No stranded threads.")
            return
        for thread in stranded:
            self.stdout.write(
                f"{thread.lesson_id}  {thread.stage:<22} {thread.topic}  needs: {', '.join(thread.missing)}"
            )
        if mark_failed:
            changed = finder.mark_failed(stranded)
            self.stdout.write(self.style.SUCCESS(f"Marked {changed} lesson{'' if changed == 1 else 's'} as failed."))
        else:
            self.stdout.write(f"{len(stranded)} stranded. Run again with --mark-failed to end them.")

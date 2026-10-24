"""Drive the lesson flow from the terminal, against the real model registry.

    manage.py flow start "Binary search" --email ada@example.com --inline
    manage.py flow answer <lesson> diagnostic --correct 5 --inline
    manage.py flow choose <lesson> cheat_sheet --inline        (after a perfect diagnostic)
    manage.py flow sheet <lesson> revision_sheet --inline      (another sheet later)
    manage.py flow show <lesson>          (add --json for the raw rows)
    manage.py flow retry <lesson> --inline
    manage.py flow runs <lesson>

`--inline` runs each step in this process instead of queueing it for a Celery worker. A lesson can be named by its
full id or by the first characters of it.
"""

import json
from abc import ABC, abstractmethod

from django.core.management import BaseCommand, CommandError
from django.db.models import CharField
from django.db.models.functions import Cast
from rest_framework.exceptions import APIException

from accounts.models import User
from lessons.models import Lesson, MaterialKind, Quiz
from lessons.reports import LessonReport
from lessons.services import LessonService, MaterialService, QuizService
from lessons.tasks import InlineTaskQueue


class Subcommand(ABC):
    name: str
    help: str

    @abstractmethod
    def add_arguments(self, parser) -> None:
        """Arguments of this subcommand."""

    @abstractmethod
    def run(self, command: "Command", options: dict) -> None: ...

    @staticmethod
    def queue(options: dict):
        return InlineTaskQueue() if options.get("inline") else None  # None: the configured (Celery) queue

    @staticmethod
    def lesson(ref: str) -> Lesson:
        matches = list(
            Lesson.objects.annotate(text_id=Cast("id", CharField())).filter(text_id__startswith=ref.lower())[:2]
        )
        if not matches:
            raise CommandError(f"No lesson matches {ref!r}.")
        if len(matches) > 1:
            raise CommandError(f"{ref!r} matches more than one lesson; give more characters.")
        return matches[0]

    @staticmethod
    def show_state(command: "Command", lesson: Lesson) -> None:
        lesson.refresh_from_db()
        command.stdout.write(
            f"stage: {lesson.stage}   route: {lesson.route or '-'}"
            + (f"   error: {lesson.error}" if lesson.error else "")
        )


class StartFlow(Subcommand):
    name, help = "start", "Start a lesson for a learner."

    def add_arguments(self, parser):
        parser.add_argument("topic")
        parser.add_argument("--email", help="The learner. Optional when there is only one user.")
        parser.add_argument("--context", default="", help="What the learner says about the topic.")

    def run(self, command, options):
        lesson, run = LessonService(queue=self.queue(options)).create(
            self.user(options.get("email")), options["topic"], options["context"]
        )
        command.stdout.write(f"lesson {lesson.id}")
        command.stdout.write(f"run {run.id}" + ("" if options["inline"] else " (queued)"))
        self.show_state(command, lesson)

    @staticmethod
    def user(email: str | None) -> User:
        users = User.objects.filter(email__iexact=email) if email else User.objects.all()[:2]
        users = list(users)
        if not users:
            raise CommandError(f"No user {email!r}." if email else "There are no users yet.")
        if len(users) > 1:
            raise CommandError("There is more than one user; pass --email.")
        return users[0]


class AnswerFlow(Subcommand):
    name, help = "answer", "Answer the quiz the lesson is waiting for."

    def add_arguments(self, parser):
        parser.add_argument("lesson")
        parser.add_argument("kind", choices=[Quiz.Kind.DIAGNOSTIC, Quiz.Kind.PREREQUISITE])
        how = parser.add_mutually_exclusive_group(required=True)
        how.add_argument("--correct", type=int, metavar="N", help="Get the first N questions right, the rest wrong.")
        how.add_argument("--answers", metavar="JSON", help='{"q1": 0, "q2": "dont_know", …}')

    def run(self, command, options):
        lesson = self.lesson(options["lesson"])
        service = QuizService(queue=self.queue(options))
        quiz = Quiz.objects.filter(lesson=lesson, kind=options["kind"]).first()
        if quiz is None:
            raise CommandError(f"The lesson has no {options['kind']} quiz yet.")
        answers = self.answers(quiz, options)
        try:
            summary, run = service.submit(lesson, options["kind"], answers)
        except APIException as exc:
            raise CommandError(str(exc.detail)) from exc
        route = f" → route {summary['route']}" if "route" in summary else ""
        command.stdout.write(f"{summary['correct']}/{summary['total']} correct{route}")
        command.stdout.write(f"run {run.id}" + ("" if options["inline"] else " (queued)"))
        self.show_state(command, lesson)

    @staticmethod
    def answers(quiz: Quiz, options: dict) -> dict:
        if options["answers"]:
            try:
                return json.loads(options["answers"])
            except json.JSONDecodeError as exc:
                raise CommandError(f"--answers is not valid JSON: {exc}") from exc
        wanted = options["correct"]
        if not 0 <= wanted <= len(quiz.questions):
            raise CommandError(f"--correct must be between 0 and {len(quiz.questions)}.")
        return {
            q["id"]: q["correct_index"] if n < wanted else (q["correct_index"] + 1) % len(q["options"])
            for n, q in enumerate(quiz.questions)
        }


class ChooseFlow(Subcommand):
    name, help = "choose", "Pick the first study sheet after a perfect diagnostic."

    def add_arguments(self, parser):
        parser.add_argument("lesson")
        parser.add_argument("kind", choices=MaterialKind.values)

    def run(self, command, options):
        lesson = self.lesson(options["lesson"])
        try:
            run = MaterialService(queue=self.queue(options)).choose(lesson, options["kind"])
        except APIException as exc:
            raise CommandError(str(exc.detail)) from exc
        command.stdout.write(f"run {run.id}" + ("" if options["inline"] else " (queued)"))
        self.show_state(command, lesson)


class SheetFlow(Subcommand):
    name, help = "sheet", "Ask for another study sheet for a ready mastery lesson."

    def add_arguments(self, parser):
        parser.add_argument("lesson")
        parser.add_argument("kind", choices=MaterialKind.values)

    def run(self, command, options):
        lesson = self.lesson(options["lesson"])
        try:
            run = MaterialService(queue=self.queue(options)).request_extra(lesson, options["kind"])
        except APIException as exc:
            raise CommandError(str(exc.detail)) from exc
        command.stdout.write(f"run {run.id}" + ("" if options["inline"] else " (queued)"))
        self.show_state(command, lesson)


class RetryFlow(Subcommand):
    name, help = "retry", "Retry a failed lesson from its last checkpoint."

    def add_arguments(self, parser):
        parser.add_argument("lesson")

    def run(self, command, options):
        lesson = self.lesson(options["lesson"])
        try:
            run = LessonService(queue=self.queue(options)).retry(lesson)
        except APIException as exc:
            raise CommandError(str(exc.detail)) from exc
        command.stdout.write(f"run {run.id}" + ("" if options["inline"] else " (queued)"))
        self.show_state(command, lesson)


class ShowFlow(Subcommand):
    name, help = "show", "Show what the flow produced for a lesson."

    def add_arguments(self, parser):
        parser.add_argument("lesson")
        parser.add_argument("--json", action="store_true", help="The stored fields as JSON.")

    def run(self, command, options):
        lesson = self.lesson(options["lesson"])
        if options["json"]:
            fields = (
                "id",
                "topic",
                "stage",
                "route",
                "level",
                "assessment",
                "prerequisites_to_cover",
                "warnings",
                "error",
            )
            command.stdout.write(json.dumps({name: getattr(lesson, name) for name in fields}, default=str, indent=2))
            return
        for line in LessonReport().lines(lesson):
            command.stdout.write(line)


class RunsFlow(Subcommand):
    name, help = "runs", "List a lesson's runs."

    def add_arguments(self, parser):
        parser.add_argument("lesson")

    def run(self, command, options):
        for run in self.lesson(options["lesson"]).runs.order_by("created_at"):
            command.stdout.write(
                f"{run.id}  {run.graph}/{run.trigger}  {run.status}" + (f"  {run.error}" if run.error else "")
            )


class Command(BaseCommand):
    help = "Drive the lesson flow from the terminal (start, answer, choose, sheet, show, retry, runs)."
    SUBCOMMANDS: list[Subcommand] = [
        StartFlow(),
        AnswerFlow(),
        ChooseFlow(),
        SheetFlow(),
        ShowFlow(),
        RetryFlow(),
        RunsFlow(),
    ]

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        for subcommand in self.SUBCOMMANDS:
            action = sub.add_parser(subcommand.name, help=subcommand.help)
            if subcommand.name != "show":
                action.add_argument("--inline", action="store_true", help="Run in this process, without a worker.")
            subcommand.add_arguments(action)

    def handle(self, *args, **options):
        subcommand = next(s for s in self.SUBCOMMANDS if s.name == options["action"])
        options.setdefault("inline", False)
        subcommand.run(self, options)

"""Making a follow-up lesson: once for each level, named without a model, from a lesson that is ready.

A follow-up is a lesson of its own, linked to the one it came from by metadata only (`created_from_lesson`,
`followup_level`). Which one to offer is decided in `offers.py`; this is what happens when the learner says yes. The
guarantee that matters is "never a second Foundation lesson": the service locks the parent and looks first, and the
database refuses a duplicate anyway (`one_followup_per_level`).
"""

import re
import uuid

from django.db import transaction

from graph.followups import FollowupTargets

from .errors import FollowupExists, WrongStage
from .metering import ActionGate, MeteredAction
from .models import Entry, FlowSettings, FollowupLevel, GraphRun, Intent, Lesson, Origin, Stage
from .services import LessonService, TaskQueue


class FollowupNames:
    """The topic of a follow-up, from a template, so it exists at once (no request calls a model) and can be checked for
    collisions. The title the learner sees is written by `lesson.plan` in the same style."""

    TEMPLATES = {"foundation": "Foundations of {topic}", "advanced": "Advanced {topic}"}
    TOPIC_MAX = 200
    #: room kept for " (99)"
    SUFFIX_ROOM = 5
    SUFFIX = re.compile(r"\s*\(\d+\)$")

    def topic_for(self, parent: Lesson, level: str) -> str:
        """ "Foundations of X" or "Advanced X"; with " (2)", " (3)"… when one of the learner's lessons has that name."""
        if level not in self.TEMPLATES:
            raise ValueError(f"Not a follow-up level: {level!r}")
        template = self.TEMPLATES[level]
        base = self.plain_topic(parent)[: self.TOPIC_MAX - len(template.format(topic="")) - self.SUFFIX_ROOM].strip()
        name = template.format(topic=base)
        taken = {self.norm(t) for t in Lesson.objects.filter(owner=parent.owner_id).values_list("topic", flat=True)}
        candidate, number = name, 1
        while self.norm(candidate) in taken:
            number += 1
            candidate = f"{name} ({number})"
        return candidate

    def plain_topic(self, parent: Lesson) -> str:
        """The parent's own topic. A follow-up's has its template and suffix on it, which a follow-up of it should not
        stack ("Advanced Foundations of X")."""
        topic = parent.topic.strip()
        if not parent.followup_level:
            return topic
        topic = self.SUFFIX.sub("", topic)
        for template in self.TEMPLATES.values():
            prefix = template.format(topic="")
            if topic.lower().startswith(prefix.lower()) and len(topic) > len(prefix):
                return topic[len(prefix) :].strip()
        return topic

    @staticmethod
    def norm(topic: str) -> str:
        return " ".join(topic.lower().split())


class FollowupService:
    def __init__(
        self,
        queue: TaskQueue | None = None,
        gate: ActionGate | None = None,
        names: FollowupNames | None = None,
        lessons: LessonService | None = None,
    ):
        # The pieces a lesson start needs (registry snapshot, gate, run dispatch) are the lesson service's own.
        self.lessons = lessons or LessonService(queue=queue, gate=gate)
        self.names = names or FollowupNames()

    def create(self, parent: Lesson, level: str, idempotency_key: str = "") -> tuple[Lesson, GraphRun]:
        """The follow-up of `level` for a ready lesson, and its queued start run. The parent is locked, so two
        requests at
        once make one lesson and the other is told which (`FollowupExists`); the gate is asked (`lesson.followup`) only
        when there is something to make, before anything is created."""
        FollowupTargets.level_for(level)  # refuses anything but foundation and advanced
        with transaction.atomic():
            parent = Lesson.objects.select_for_update().get(pk=parent.pk)
            if parent.stage != Stage.READY:
                raise WrongStage("A follow-up can be made once the lesson is ready.")
            if existing := parent.followups.filter(followup_level=level).first():
                raise FollowupExists(existing.pk)
            snapshot = self.lessons.resolver.snapshot()
            self.lessons.require_models(snapshot, Entry.FOLLOWUP, followup_level=level)
            lesson_id = uuid.uuid4()
            authorization = self.lessons.metering.authorize(
                parent.owner,
                MeteredAction.LESSON_FOLLOWUP,
                size=self.size_of(level),
                subject_id=lesson_id,
                client_key=idempotency_key,
            )
            with self.lessons.metering.guard(authorization):
                lesson = Lesson.objects.create(
                    id=lesson_id,
                    owner=parent.owner,
                    topic=self.names.topic_for(parent, level),
                    user_context=f"A follow-up to my lesson on {(parent.title or parent.topic)[:200]}.",
                    entry=Entry.FOLLOWUP,
                    intent=Intent.LESSON,
                    origin=Origin.FOLLOWUP,
                    created_from_lesson=parent,
                    followup_level=FollowupLevel(level),
                    config_snapshot=snapshot.to_json(),
                    settings_snapshot=FlowSettings.load().snapshot(),
                )
                run = GraphRun.objects.create(
                    lesson=lesson,
                    graph=GraphRun.Graph.FLOW,
                    trigger=GraphRun.Trigger.START,
                    payload=self.lessons.metering.payload(authorization),
                )
        self.lessons.dispatcher.dispatch(run)
        return lesson, run

    @staticmethod
    def size_of(level: str) -> dict:
        """What `lesson.followup` is asked with. A follow-up has no quiz, so it covers the whole lesson."""
        return {
            "entry": "followup", "intent": "lesson", "origin": "followup", "covers": "all", "followup_level": level,
        }  # fmt: skip

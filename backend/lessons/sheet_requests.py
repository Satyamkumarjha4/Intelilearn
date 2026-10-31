"""Which sheets are asked for, and what they will rest on, for the services that start sheet work.

A learner can ask for a cheat sheet, a revision sheet, or both, in one request. The practice sheet is not offered any
more (the sheets that exist can still be opened). Where the request came from decides what the sheets rest on: the
lesson's own content, the quick check's concepts, or nothing but the topic and the level the learner chose. The gate is
told which (`sheet.generate` and `lesson.create` carry it as `grounding`), so a later pricing feature can price them
alike or differently.
"""

from collections.abc import Iterable

from graph.sheets import SheetKinds

from .models import Entry, GraphRun, Lesson

LESSON, QUIZ, NONE = "lesson", "quiz", "none"


class SheetRequest:
    #: what can be asked for, in the order the sheets are written
    OFFERED = SheetKinds.CHOICE

    @classmethod
    def kinds(cls, asked: str | Iterable[str]) -> list[str]:
        """The kinds asked for, each once, cheat sheet first. `ValueError` for none, or one that is not offered."""
        wanted = [asked] if isinstance(asked, str) else list(asked or [])
        unknown = [kind for kind in wanted if kind not in cls.OFFERED]
        if not wanted or unknown:
            raise ValueError(f"Ask for a cheat sheet, a revision sheet, or both; not {unknown or 'nothing'}.")
        return [kind for kind in cls.OFFERED if kind in wanted]

    @staticmethod
    def of(lesson: Lesson) -> list[str]:
        """The sheets a lesson that asked for sheets was started with (its first run carries them)."""
        first = GraphRun.objects.for_subject(lesson).filter(trigger=GraphRun.Trigger.START).order_by("created_at")
        run = first.first()
        asked = ((run.payload if run else {}).get("input") or {}).get("sheet_kinds")
        return SheetKinds.of({"sheet_kinds": asked})


class SheetGroundingHint:
    @staticmethod
    def of(lesson: Lesson) -> str:
        """What the sheets of this lesson rest on: its pages, else the quick check it took, else the topic alone."""
        if lesson.plan and lesson.pages:
            return LESSON
        return QUIZ if lesson.entry == Entry.DIAGNOSTIC else NONE

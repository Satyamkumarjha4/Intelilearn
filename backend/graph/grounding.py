"""What a study sheet is made from (Strategy by situation, one class).

A sheet is asked for in three situations. From a lesson that has pages, it follows that lesson (its terms and
notation). From a topic after a quick check, or after a perfect score when the learner chose sheets, it rests on what
the quiz covered. From a topic with only a self-rating there is nothing to ground it in but the topic and the level the
learner chose. `SheetGrounding.of(state)` finds which one applies and reads it once, so the nodes that write the sheets
and the prompt that asks the model share one description and the sheets of one request are grounded alike.
"""

from dataclasses import asdict, dataclass, field

from lessons.models import Lesson, Route

from .nodes.mastery import DiagnosticConcepts
from .schemas.lesson import PAGE_KEYS

LESSON, QUIZ, NONE = "lesson", "quiz", "none"
MASTERED, LEVEL = "mastered", "level"


@dataclass(frozen=True)
class Grounding:
    kind: str  # lesson, quiz or none
    audience: str  # mastered (aced the quick check) or level
    concepts: list[str] = field(default_factory=list)
    level: str = ""
    known: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    lesson: dict | None = None  # title, level, summary and the pages' headings, for a sheet made from a lesson

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Grounding":
        return cls(**data)


class SheetGrounding:
    @classmethod
    def of(cls, state: dict) -> Grounding:
        lesson = Lesson.objects.get(pk=state["lesson_id"])
        assessment = state.get("assessment") or {}
        level = assessment.get("level") or lesson.level
        audience = MASTERED if lesson.route == Route.MASTERY or state.get("mastery_choice") == "sheets" else LEVEL
        known, gaps = list(assessment.get("known_concepts") or []), list(assessment.get("gaps") or [])
        if lesson.plan and lesson.pages:
            content = cls.lesson_content(lesson)
            return Grounding(LESSON, audience, cls.plan_concepts(lesson.plan), level, lesson=content)
        if concepts := list(dict.fromkeys(DiagnosticConcepts.of(state))):  # the quiz asks about a concept twice
            return Grounding(QUIZ, audience, concepts, level, known, gaps)
        return Grounding(NONE, audience, [], level, known, gaps)

    @staticmethod
    def plan_concepts(plan: dict) -> list[str]:
        """Each concept of the plan once, in the order it is taught."""
        return list(dict.fromkeys(item["concept"] for page in plan["pages"] for item in page["outline"]))

    @staticmethod
    def lesson_content(lesson: Lesson) -> dict:
        pages = [lesson.pages[key] for key in PAGE_KEYS if key in lesson.pages]
        return {
            "title": lesson.title or lesson.plan["title"],
            "level": lesson.level,
            "summary": lesson.plan["summary"],
            "pages": [
                {"title": page["title"], "headings": [section["heading"] for section in page["sections"]]}
                for page in pages
            ],
        }

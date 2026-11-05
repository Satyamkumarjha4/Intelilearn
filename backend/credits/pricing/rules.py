"""The price rule of each metered action: the plan's pricing matrix (§5.4) as code.

A rule turns the size hints an action is asked with into the keys of the price table it is made of; the shared `quote`
(Template Method) reads the hints strictly, looks the keys up in the `PriceBook`, and returns the lines. A new action
is a
new rule and a line in `PriceRules`, never an `if` somewhere else.

What a rule must get right is which hint matters. Study sheets are priced by the number of sheets and never by the
score,
the recommended discount is taken where the lesson is made, the extra for a quiz is charged once whether it is from
lessons
or has the warm-up, and a sheet rests on a lesson's pages for one extra credit only when it really does.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from lessons.metering import MeteredAction

from .book import PriceBook
from .hints import HintReader, UnknownHints
from .values import PriceQuote

GROUNDINGS = ("lesson", "quiz", "none")
QUIZ_COUNTS = (5, 10, 15, 20, 25, 30)
QUIZ_TIERS = {
    5: "quiz.tier_5",
    10: "quiz.tier_10",
    15: "quiz.tier_10",
    20: "quiz.tier_20",
    25: "quiz.tier_20",
    30: "quiz.tier_20",
}
SOURCES = ("topic", "lessons")


class PriceRule(ABC):
    action: ClassVar[MeteredAction]
    #: every hint the services send with this action, whether or not the price reads it
    HINTS: ClassVar[tuple[str, ...]]

    def __init__(self, book: PriceBook | None = None):
        self.book = book or PriceBook()

    def quote(self, size) -> PriceQuote:
        return PriceQuote(tuple(self.book.line(key) for key in self.keys(HintReader(size, self.HINTS))))

    @abstractmethod
    def keys(self, hints: HintReader) -> list[str]:
        """The rows of the price table this ask is made of, in order. Reads every hint, so a bad one is refused."""


@dataclass(frozen=True)
class CreateFacts:
    entry: str
    intent: str
    origin: str
    sheets: int | None


class LessonCreatePrice(PriceRule):
    action = MeteredAction.LESSON_CREATE
    HINTS = ("entry", "intent", "origin", "covers", "sheets", "grounding")

    def facts(self, size) -> CreateFacts:
        hints = HintReader(size, self.HINTS)
        entry = hints.one_of("entry", ("diagnostic", "self_rating", "quiz_result"))
        intent = hints.one_of("intent", ("lesson", "sheets"), default="lesson")
        origin = hints.one_of("origin", ("direct", "recommendation", "quiz_result"), default="direct")
        hints.one_of("covers", ("diagnostic", "all"), default=None)
        hints.one_of("grounding", GROUNDINGS, default=None)
        sheets = hints.whole("sheets", 1, 2, default=None)
        if intent == "sheets" and sheets is None:
            raise UnknownHints("sheets", "is needed to price study sheets.")
        return CreateFacts(entry, intent, origin, sheets)

    def keys(self, hints: HintReader) -> list[str]:
        return self._keys(self.facts(hints.size))

    @staticmethod
    def _keys(facts: CreateFacts) -> list[str]:
        recommended = facts.origin == "recommendation"
        if facts.intent == "sheets":
            # Sheets after a Quick check are paid for in its two stages (3 now, 0 or 2 later); otherwise 2 a sheet at
            # once.
            return ["lesson.check"] if facts.entry == "diagnostic" else ["sheet.each"] * facts.sheets
        if facts.entry == "diagnostic":
            return ["lesson.check_recommended" if recommended else "lesson.check"]
        if facts.entry == "self_rating":
            return ["lesson.full_recommended" if recommended else "lesson.full"]
        return ["lesson.full_from_quiz"]


class LessonContinuePrice(PriceRule):
    action = MeteredAction.LESSON_CONTINUE
    HINTS = ("choice", "perfect", "intent", "sheets", "grounding")

    def keys(self, hints: HintReader) -> list[str]:
        choice = hints.one_of("choice", ("lesson", "sheets_only"))
        hints.flag("perfect", default=None)
        hints.one_of("intent", ("lesson", "sheets"), default=None)
        hints.one_of("grounding", GROUNDINGS, default=None)
        sheets = hints.whole("sheets", 1, 2, default=None)
        if choice == "lesson":
            return ["lesson.rest"]
        if sheets is None:
            raise UnknownHints("sheets", "is needed to price study sheets.")
        # By the number of sheets and never by the score: both sheets 2, one sheet nothing more.
        return ["sheets.after_check" if sheets == 2 else "sheets.after_check_single"]


class LessonFollowupPrice(PriceRule):
    action = MeteredAction.LESSON_FOLLOWUP
    HINTS = ("entry", "intent", "origin", "covers", "followup_level")

    def keys(self, hints: HintReader) -> list[str]:
        hints.one_of("entry", ("followup",), default=None)
        hints.one_of("intent", ("lesson",), default=None)
        hints.one_of("origin", ("followup",), default=None)
        hints.one_of("covers", ("all",), default=None)
        return [f"followup.{hints.one_of('followup_level', ('foundation', 'advanced'))}"]


class TestRetakePrice(PriceRule):
    __test__ = False  # not a pytest class, whatever its name suggests
    action = MeteredAction.TEST_RETAKE
    HINTS = ("question_count", "attempt_no")

    def keys(self, hints: HintReader) -> list[str]:
        hints.whole("question_count", 1, default=None)
        hints.whole("attempt_no", 2, default=None)  # attempt 1 is part of the lesson and never asked
        return ["test.retake"]


class QuizCreatePrice(PriceRule):
    action = MeteredAction.QUIZ_CREATE
    HINTS = ("num_questions", "source_type", "sources", "level_mode", "has_subjective")

    def keys(self, hints: HintReader) -> list[str]:
        count = hints.whole("num_questions", allowed=QUIZ_COUNTS)
        source = hints.one_of("source_type", SOURCES)
        mode = hints.one_of("level_mode", ("self_rating", "calibration", "existing_score"))
        hints.whole("sources", 0, default=None)
        hints.flag("has_subjective", default=None)
        # One extra credit, once: for a quiz made from lessons, or one with the warm-up (never both on top of each
        # other).
        return [QUIZ_TIERS[count], *(["quiz.extra"] if source == "lessons" or mode == "calibration" else [])]


class QuizRetakePrice(PriceRule):
    action = MeteredAction.QUIZ_RETAKE
    HINTS = ("num_questions", "source_type")

    def keys(self, hints: HintReader) -> list[str]:
        count = hints.whole("num_questions", allowed=QUIZ_COUNTS)
        source = hints.one_of("source_type", SOURCES)
        return [QUIZ_TIERS[count], *(["quiz.extra"] if source == "lessons" else [])]


class SheetGeneratePrice(PriceRule):
    action = MeteredAction.SHEET_GENERATE
    HINTS = ("sheets", "grounding")

    def keys(self, hints: HintReader) -> list[str]:
        sheets = hints.whole("sheets", 1, 2)
        grounding = hints.one_of("grounding", GROUNDINGS)
        return ["sheet.each"] * sheets + (["sheet.grounded_extra"] if grounding == "lesson" else [])


class PriceRules:
    """The registry: one rule for each metered action."""

    RULES: ClassVar[dict[MeteredAction, type[PriceRule]]] = {
        MeteredAction.LESSON_CREATE: LessonCreatePrice,
        MeteredAction.LESSON_CONTINUE: LessonContinuePrice,
        MeteredAction.LESSON_FOLLOWUP: LessonFollowupPrice,
        MeteredAction.TEST_RETAKE: TestRetakePrice,
        MeteredAction.QUIZ_CREATE: QuizCreatePrice,
        MeteredAction.QUIZ_RETAKE: QuizRetakePrice,
        MeteredAction.SHEET_GENERATE: SheetGeneratePrice,
    }

    @classmethod
    def for_action(cls, action, book: PriceBook | None = None) -> PriceRule:
        return cls.RULES[action](book)

    @classmethod
    def all(cls, book: PriceBook | None = None) -> list[PriceRule]:
        return [rule(book) for rule in cls.RULES.values()]

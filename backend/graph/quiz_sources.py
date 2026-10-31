"""What a quick quiz made from lessons is built from (plan D18). Pure.

A quiz can combine up to ten lessons. Every lesson must add at least one question, the remainder goes to the lessons the
learner made most recently, and the model must never be handed lesson text: a prompt carrying ten whole lessons would
cost a lot and bury the concepts. So each lesson is boiled down, in code and from its stored plan, to a short summary
that fits a token budget, the least important concepts dropped first.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from .levels import Level


class SourceSplitError(ValueError):
    """The lessons picked cannot make a quiz of that size."""


class TokenEstimate:
    """A cheap estimate of the tokens in a text: characters divided by four, rounded up. No tokenizer, no model."""

    @staticmethod
    def of(text: str) -> int:
        return (len(text) + 3) // 4


class SourceSplit:
    """Shares the questions of a quiz between its lessons: evenly, with the remainder to the most recent lessons, one
    each, and never a lesson that adds nothing."""

    DEFAULT_MAX = 10

    def __init__(self, max_lessons: int = DEFAULT_MAX):
        self.max_lessons = max_lessons

    def shares(self, count: int, lessons: Sequence[tuple[str, datetime]]) -> dict[str, int]:
        """`lessons`: (key, created_at) pairs. → each key's number of questions, in the order the lessons were given."""
        keys = [key for key, _ in lessons]
        if not keys:
            raise SourceSplitError("Pick at least one lesson.")
        if len(set(keys)) != len(keys):
            raise SourceSplitError("Each lesson can be picked once.")
        if len(keys) > self.max_lessons:
            raise SourceSplitError(f"A quiz can combine at most {self.max_lessons} lessons.")
        if count < len(keys):
            raise SourceSplitError(f"A quiz needs at least as many questions as lessons ({len(keys)}).")
        base, remainder = divmod(count, len(keys))
        newest_first = sorted(lessons, key=lambda lesson: (lesson[1], lesson[0]), reverse=True)
        extra = {key for key, _ in newest_first[:remainder]}
        return {key: base + (1 if key in extra else 0) for key in keys}


@dataclass(frozen=True)
class ConceptSummary:
    """A lesson as the question writer sees it: its title, level and what it covers, and the concepts of its plan."""

    title: str
    level: str
    summary: str
    concepts: list[dict] = field(default_factory=list)  # {concept, heading, notes, page}, in teaching order
    dropped: list[str] = field(default_factory=list)  # the concepts that did not fit, lowest priority first

    def text(self) -> str:
        lines = [f"{self.title} (level: {self.level})", self.summary]
        if self.concepts:
            lines.append("Concepts, in teaching order:")
            lines += [f"- {c['concept']}: {c['notes']}" for c in self.concepts]
        return "\n".join(line for line in lines if line)

    def as_dict(self) -> dict:
        return {
            "title": self.title, "level": self.level, "summary": self.summary,
            "concepts": [dict(c) for c in self.concepts], "dropped": list(self.dropped),
        }  # fmt: skip

    @classmethod
    def from_dict(cls, data: dict) -> "ConceptSummary":
        return cls(data["title"], data["level"], data["summary"], list(data["concepts"]), list(data["dropped"]))


class ConceptSummaries:
    """Builds a `ConceptSummary` from a lesson's stored plan, never from its pages."""

    #: which page's concepts matter most for a quiz: what the lesson is about, then how it starts, then how it ends
    PRIORITY: ClassVar[dict[str, int]] = {"core": 0, "introduction": 1, "advanced": 2}
    SUMMARY_CHARS = 400

    def of(self, plan: dict, budget: int) -> ConceptSummary:
        """The summary within `budget` tokens. The header (title, level, what the lesson covers) is always there; the
        concepts are added in order of priority while they fit, and the rest are listed as dropped."""
        header = ConceptSummary(
            plan.get("title", ""), str(plan.get("level", "")), str(plan.get("summary", ""))[: self.SUMMARY_CHARS]
        )
        concepts = self._concepts(plan)
        ranked = sorted(range(len(concepts)), key=lambda n: (self.PRIORITY.get(concepts[n]["page"], 3), n))
        kept: list[int] = []
        for number in ranked:
            trial = sorted([*kept, number])
            candidate = self._with(header, [concepts[n] for n in trial])
            if TokenEstimate.of(candidate.text()) > budget:
                break
            kept = trial
        left_out = [concepts[n]["concept"] for n in reversed(ranked) if n not in kept]
        return ConceptSummary(header.title, header.level, header.summary, [concepts[n] for n in kept], left_out)

    @staticmethod
    def _with(header: ConceptSummary, concepts: list[dict]) -> ConceptSummary:
        return ConceptSummary(header.title, header.level, header.summary, concepts)

    @staticmethod
    def _concepts(plan: dict) -> list[dict]:
        seen: set[str] = set()
        found = []
        for page in plan.get("pages") or []:
            for item in page.get("outline") or []:
                name = str(item.get("concept", "")).strip()
                if name and name not in seen:
                    seen.add(name)
                    found.append({
                        "concept": name, "heading": item.get("heading", ""), "notes": item.get("notes", ""),
                        "page": page.get("key", ""),
                    })  # fmt: skip
        return found


class LevelMean:
    """The level a quiz made from several lessons reports when each lesson has its own: the middle one, a half rounded
    up. (The questions are still written at each lesson's level; this is only the level the quiz shows.)"""

    @staticmethod
    def of(levels: Sequence) -> Level:
        if not levels:
            raise ValueError("A level needs at least one level to take the middle of.")
        order = list(Level)
        ranks = [order.index(Level.parse(level)) for level in levels]
        return order[(2 * sum(ranks) + len(ranks)) // (2 * len(ranks))]

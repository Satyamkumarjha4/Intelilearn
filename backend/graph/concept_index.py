"""Which page of a lesson teaches each of its concepts (plan §7.1, §9.6, R18). Pure: no model, no ORM.

A quiz or a test result names the concepts a learner got wrong; the app links each to the page that teaches it. The plan
is the one place that says which page a concept belongs to (every outline concept is on exactly one page), and the
pages say where on the page it is taught. So an entry is placed, in this order, by:

1. a section the page writer tagged with the concept (`Section.concepts`),
2. the section whose heading is the outline's heading,
3. the section that talks about the concept the most.

A concept that no section covers is still listed, without a page, so a link falls back to the lesson as a whole.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from .normal import Normal
from .validators.base import TextRules


@dataclass(frozen=True)
class ConceptEntry:
    concept: str
    page: str  # introduction, core or advanced; empty when no section could be found for it
    heading: str  # the section's heading; empty when page is
    summary: str  # the outline's notes: what the concept covers

    def as_dict(self) -> dict:
        return {"concept": self.concept, "page": self.page, "heading": self.heading, "summary": self.summary}


@dataclass(frozen=True)
class ConceptIndex:
    entries: tuple[ConceptEntry, ...] = ()

    @classmethod
    def build(cls, plan: dict | None, pages: dict | None) -> "ConceptIndex":
        """The index of a lesson from its plan and its pages (either may be missing: the concepts are then unplaced)."""
        entries: list[ConceptEntry] = []
        seen: set[str] = set()
        for plan_page in (plan or {}).get("pages") or []:
            sections = ((pages or {}).get(plan_page.get("key")) or {}).get("sections") or []
            for item in plan_page.get("outline") or []:
                name = str(item.get("concept", "")).strip()
                if not name or TextRules.norm(name) in seen:
                    continue
                seen.add(TextRules.norm(name))
                section = cls._section_for(item, name, sections)
                entries.append(
                    ConceptEntry(
                        name,
                        str(plan_page["key"]) if section else "",
                        str(section.get("heading", "")) if section else "",
                        str(item.get("notes", "")),
                    )
                )
        return cls(tuple(entries))

    @classmethod
    def _section_for(cls, item: dict, name: str, sections: Sequence[dict]) -> dict | None:
        wanted = TextRules.norm(name)
        for section in sections:
            if wanted in {TextRules.norm(tag) for tag in section.get("concepts") or [] if isinstance(tag, str)}:
                return section
        heading = TextRules.norm(str(item.get("heading", "")))
        for section in sections:
            if heading and TextRules.norm(str(section.get("heading", ""))) == heading:
                return section
        scored = [
            (cls._talks_about(section, name), -number, section)
            for number, section in enumerate(sections)
            if TextRules.mentions(f"{section.get('heading', '')} {section.get('body', '')}", name)
        ]
        return max(scored, key=lambda row: row[:2])[2] if scored else None

    @staticmethod
    def _talks_about(section: dict, name: str) -> int:
        """How many of the concept's words the section's heading and body use: a tie goes to the earlier section."""
        words = [w for w in TextRules.norm(name).split() if len(w) > 3] or TextRules.norm(name).split()
        haystack = TextRules.norm(f"{section.get('heading', '')} {section.get('body', '')}")
        return sum(word in haystack for word in words)

    @classmethod
    def from_json(cls, stored) -> "ConceptIndex":
        """Read a stored index. Anything that is not one (a lesson from before the index, a damaged value) is empty."""
        if not isinstance(stored, list):
            return cls()
        entries = []
        for row in stored:
            if not isinstance(row, dict) or not isinstance(row.get("concept"), str):
                continue
            page, heading = row.get("page"), row.get("heading")
            if not isinstance(page, str) or not isinstance(heading, str):
                continue
            summary = row.get("summary")
            entries.append(ConceptEntry(row["concept"], page, heading, summary if isinstance(summary, str) else ""))
        return cls(tuple(entries))

    def to_json(self) -> list[dict]:
        return [entry.as_dict() for entry in self.entries]

    def names(self) -> list[str]:
        return [entry.concept for entry in self.entries]

    def find(self, concept: str) -> ConceptEntry | None:
        wanted = TextRules.norm(str(concept))
        return next((e for e in self.entries if wanted and TextRules.norm(e.concept) == wanted), None)

    #: words that say nothing about which concept is meant, left out when two names are compared by their words
    FILLER: ClassVar[frozenset[str]] = frozenset({"a", "an", "the", "of", "in", "on", "to", "and", "or", "for", "with"})
    NEAR: ClassVar[float] = 0.3  # the share of their words two names must have in common (Jaccard) to be called near

    def nearest(self, concept: str) -> ConceptEntry | None:
        """The concept of the plan a free-text concept is nearest to: the same name (case and spacing aside), else the
        one that shares the largest part of its words, the earlier one on a tie; None when no one shares enough. This is
        how an old lesson's test, whose questions named concepts in the model's own words, is linked to a page.
        No model is involved."""
        if exact := self.find(concept):
            return exact
        wanted = self._words(concept)
        scored = [
            (len(wanted & self._words(e.concept)) / len(wanted | self._words(e.concept)), e)
            for e in self.entries
            if wanted
        ]
        best = max(scored, key=lambda pair: pair[0], default=(0.0, None))
        return best[1] if best[0] >= self.NEAR else None

    @classmethod
    def _words(cls, name: str) -> frozenset[str]:
        return frozenset(word for word in Normal.text(str(name)).split() if len(word) > 1 and word not in cls.FILLER)

    @property
    def placed(self) -> int:
        return sum(1 for entry in self.entries if entry.page)

    @property
    def unplaced(self) -> int:
        return len(self.entries) - self.placed

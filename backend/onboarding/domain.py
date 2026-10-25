"""The plain values of the topic suggestions: what is asked, what a topic is, what comes back."""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class Source(StrEnum):
    """Where the four topics came from: the curated catalogue, a model, or the catalogue again because a model
    failed."""

    CATALOGUE = "catalogue"
    AI = "ai"
    FALLBACK = "fallback"


class GradeParser:
    """Reads a school class out of what a learner typed ("Class 9", "9th", "grade 9, CBSE")."""

    CLASSES = range(6, 13)
    _NUMBER = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")

    @classmethod
    def parse(cls, text: str) -> int | None:
        """The first number in `text` if it is a class the catalogue covers, else None."""
        match = cls._NUMBER.search(text)
        return int(match.group(1)) if match and int(match.group(1)) in cls.CLASSES else None


class Slug:
    """A short, key-safe form of free text: lower case, words joined by dashes. Any script; bounded length."""

    MAX_LENGTH = 60
    _DASHES = re.compile(r"-{2,}")

    @classmethod
    def of(cls, text: str) -> str:
        # Letters, digits and the combining marks that belong to them (vowel signs in Hindi, accents) stay; the rest
        # separates.
        kept = "".join(
            ch if ch.isalnum() or unicodedata.category(ch).startswith("M") else "-" for ch in text.casefold()
        )
        return cls._DASHES.sub("-", kept).strip("-")[: cls.MAX_LENGTH].strip("-")


@dataclass(frozen=True)
class SuggestionRequest:
    """What the learner said about themselves, before their profile is saved."""

    education_level: str
    goal: str
    preferred_language: str = "en"
    grade_or_year: str = ""
    field_of_study: str = ""
    page: int = 0

    @property
    def english(self) -> bool:
        return self.preferred_language == "en"

    @property
    def school_class(self) -> int | None:
        return GradeParser.parse(self.grade_or_year) if self.education_level == "school" else None

    @property
    def grade_label(self) -> str:
        """The class or year as the reason text says it: "Class 9" for a school class, else the learner's own words."""
        if self.school_class is not None:
            return f"Class {self.school_class}"
        return " ".join(self.grade_or_year.split())

    @property
    def field_slug(self) -> str:
        return Slug.of(self.field_of_study)

    @property
    def has_field(self) -> bool:
        """A field with no letters in it ("???") is as good as none."""
        return bool(self.field_slug)


@dataclass(frozen=True)
class Topic:
    """One suggested first topic. `title` is in the learner's language, `title_en` is the English one."""

    title: str
    title_en: str
    subject: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "title_en": self.title_en, "subject": self.subject, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict) -> "Topic":
        return cls(data["title"], data["title_en"], data["subject"], data["reason"])


@dataclass(frozen=True)
class Suggestions:
    source: Source
    topics: tuple[Topic, ...]
    has_more: bool

    def as_dict(self) -> dict:
        return {
            "source": str(self.source),
            "topics": [topic.as_dict() for topic in self.topics],
            "has_more": self.has_more,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Suggestions":
        return cls(Source(data["source"]), tuple(Topic.from_dict(t) for t in data["topics"]), bool(data["has_more"]))

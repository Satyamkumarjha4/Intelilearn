"""The curated catalogue (`catalogue.json`): the instant, free source of first topics, and the fallback when a model
fails.

The file is data, not code: a new class, field family or list is a JSON edit. It is validated when it loads, so a
malformed edit fails the tests (and the first request), never a learner's onboarding.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .domain import GradeParser

CATALOGUE_PATH = Path(__file__).with_name("catalogue.json")
LEVELS = ("undergraduate", "postgraduate")


class CatalogueError(ValueError):
    pass


@dataclass(frozen=True)
class CatalogueItem:
    subject: str
    title: str


class FieldFamilies:
    """Matches a field of study to a family by keywords. The first family with a keyword in the field wins, so the file
    lists the more specific families first. Keywords are whole words or phrases ("it" is not in "itinerant")."""

    _NOT_WORD = re.compile(r"[\W_]+")

    def __init__(self, families: list[tuple[str, list[str]]]):
        self._families = [(slug, [self._normalise(keyword) for keyword in keywords]) for slug, keywords in families]

    def match(self, field_of_study: str) -> str | None:
        text = f" {self._normalise(field_of_study)} "
        for slug, keywords in self._families:
            if any(f" {keyword} " in text for keyword in keywords):
                return slug
        return None

    @classmethod
    def _normalise(cls, text: str) -> str:
        return cls._NOT_WORD.sub(" ", text.casefold()).strip()


class Catalogue:
    MIN_TOPICS = 4  # a page is four topics

    _default: "Catalogue | None" = None

    def __init__(self, data: dict):
        school = self._section(data, "school")
        self._classes = {
            grade: self._items(
                f"class {grade}",
                self._get(self._get(school, "classes", "school.classes"), str(grade), f"class {grade}"),
            )
            for grade in GradeParser.CLASSES
        }
        self._school_general = self._items("school general", self._get(school, "general", "school.general"))

        higher = self._section(data, "higher_education")
        general = self._get(higher, "general", "higher_education.general")
        self._general = {
            level: self._items(f"general {level}", self._get(general, level, f"higher_education.general.{level}"))
            for level in LEVELS
        }
        self._family_lists: dict[str, dict[str, tuple[CatalogueItem, ...]]] = {}
        keywords = []
        for family in self._get(higher, "families", "higher_education.families"):
            slug = self._get(family, "slug", "a family")
            self._family_lists[slug] = {
                level: self._items(f"family {slug} {level}", self._get(family, level, f"family {slug} {level}"))
                for level in LEVELS
            }
            words = self._get(family, "keywords", f"family {slug} keywords")
            if not words or not all(isinstance(word, str) and word.strip() for word in words):
                raise CatalogueError(f"family {slug}: needs a list of keywords")
            keywords.append((slug, words))
        self.families = FieldFamilies(keywords)

        self._professional = self._items("professional", self._get(data, "professional", "professional"))
        self._interview_prep = self._items("interview_prep", self._get(data, "interview_prep", "interview_prep"))
        self._self_learner = self._items("self_learner", self._get(data, "self_learner", "self_learner"))

    @classmethod
    def default(cls) -> "Catalogue":
        if cls._default is None:
            cls._default = cls(json.loads(CATALOGUE_PATH.read_text(encoding="utf-8")))
        return cls._default

    def school(self, grade: int | None) -> tuple[CatalogueItem, ...]:
        """The topics of a class; the general school list for no class, or one the catalogue does not cover."""
        return self._classes.get(grade, self._school_general) if grade is not None else self._school_general

    def general(self, level: str) -> tuple[CatalogueItem, ...]:
        return self._general[level]

    def family(self, slug: str, level: str) -> tuple[CatalogueItem, ...]:
        return self._family_lists[slug][level]

    def professional(self) -> tuple[CatalogueItem, ...]:
        return self._professional

    def interview_prep(self) -> tuple[CatalogueItem, ...]:
        return self._interview_prep

    def self_learner(self) -> tuple[CatalogueItem, ...]:
        return self._self_learner

    @staticmethod
    def _get(mapping, key, where: str):
        if not isinstance(mapping, dict) or key not in mapping:
            raise CatalogueError(f"{where} is missing")
        return mapping[key]

    @classmethod
    def _section(cls, data: dict, key: str) -> dict:
        return cls._get(data, key, key)

    @classmethod
    def _items(cls, where: str, raw) -> tuple[CatalogueItem, ...]:
        if not isinstance(raw, list):
            raise CatalogueError(f"{where} must be a list of topics")
        items = []
        for index, entry in enumerate(raw):
            subject, title = (entry.get("subject"), entry.get("title")) if isinstance(entry, dict) else (None, None)
            if not (isinstance(subject, str) and subject.strip() and isinstance(title, str) and title.strip()):
                raise CatalogueError(f"{where}[{index}] needs a subject and a title")
            items.append(CatalogueItem(subject.strip(), title.strip()))
        if len(items) < cls.MIN_TOPICS:
            raise CatalogueError(f"{where} needs at least {cls.MIN_TOPICS} topics, it has {len(items)}")
        return tuple(items)

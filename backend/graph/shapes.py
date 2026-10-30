"""Lesson shapes (Strategy): what each of the lesson's three page slots is *for*, by the learner's level.

The slots keep their keys (`introduction`, `core`, `advanced`); only their roles change. The plan prompt, the page
writers and the plan validator ask the shape instead of hard-coding the roles. The test is not part of a shape: it is
the same fixed blueprint for every level (docs/architecture/design.md §4.20).
"""

from abc import ABC
from dataclasses import dataclass
from typing import Any, ClassVar

from .levels import Level, LevelScheme
from .schemas.lesson import PAGE_KEYS


@dataclass(frozen=True)
class PageRole:
    title: str
    brief: str


class LessonShape(ABC):
    level: ClassVar[Level]
    #: a Beginner lesson opens with the prerequisites, so they are planned when no quiz found them
    requires_prerequisites: ClassVar[bool] = False
    roles: ClassVar[dict[str, PageRole]]
    #: for a lesson whose level was not found by a quiz, so there is no assessment to say where to begin
    start_point: ClassVar[str]
    author_notes: ClassVar[str]
    summary: ClassVar[str]

    @property
    def page_keys(self) -> tuple[str, ...]:
        return tuple(self.roles)

    def role(self, key: str) -> PageRole:
        return self.roles[key]

    def describe(self) -> str:
        """For the plan prompt: who the lesson is for and what each slot does."""
        slots = "\n".join(f'- "{key}": {role.title}. {role.brief}' for key, role in self.roles.items())
        return f"This is a {self.level.label} lesson: {self.summary}\n{slots}"


class BeginnerShape(LessonShape):
    level = Level.BEGINNER
    requires_prerequisites = True
    summary = "for someone who is new to the topic, so nothing is assumed and the first page builds the ground."
    roles = {
        "introduction": PageRole(
            "Prerequisites and introduction",
            "A friendly hook, why the topic matters, then every prerequisite taught from scratch, then an overview.",
        ),
        "core": PageRole("Core", "The core concepts, one small step at a time, with a worked example for each."),
        "advanced": PageRole("A taste of what is next", "A gentle look ahead, so the learner sees where this leads."),
    }
    start_point = "Start from the very beginning: what the topic is, in plain words, before any technical term."
    author_notes = (
        "Assume no prior knowledge. Define every term the first time it appears, use everyday analogies, keep steps "
        "small, and encourage the learner often."
    )


class FoundationShape(LessonShape):
    level = Level.FOUNDATION
    summary = "for someone who knows a little, so the basics are refreshed fast and the effort goes into using them."
    roles = {
        "introduction": PageRole(
            "Introduction and a quick recap", "Why the topic matters, then a short recap of the basics it builds on."
        ),
        "core": PageRole("Core concepts, step by step", "The core concepts with worked examples and common mistakes."),
        "advanced": PageRole("Going further", "The next ideas up, and a few harder examples to stretch the learner."),
    }
    start_point = "Begin with the basics the learner has probably met, then move quickly to the core ideas."
    author_notes = (
        "The learner knows some basics but gets lost quickly. Recap briefly, then explain with clear examples and "
        "name the mistakes people usually make."
    )


class ProficientShape(LessonShape):
    level = Level.PROFICIENT
    summary = "for someone who is solid on most of it, so there is little recap and the depth is in the details."
    roles = {
        "introduction": PageRole(
            "A short overview", "A brief orientation that names what is covered and why it matters."
        ),
        "core": PageRole("Core concepts in depth", "The core concepts with precise definitions and harder examples."),
        "advanced": PageRole("Edge cases and trade-offs", "Edge cases, trade-offs and real-world use."),
    }
    start_point = "Skip the basics. Begin with the core ideas and go straight to how they are used."
    author_notes = (
        "The learner is comfortable with the basics. Be precise and brisk, use harder examples, and point out the "
        "subtle cases."
    )


class ExpertShape(LessonShape):
    level = Level.EXPERT
    summary = "for someone who could teach it, so it is a sharp tour of depth, nuance and the hard cases."
    roles = {
        "introduction": PageRole(
            "Brief orientation", "Two or three sentences of framing and a map of what is covered."
        ),
        "core": PageRole("Depth and nuance", "The finer points, derivations or reasoning, and how experts think."),
        "advanced": PageRole(
            "Hard cases and real-world use", "The hardest cases, open questions and how it is used in practice."
        ),
    }
    start_point = "Begin at an advanced level: assume the standard material and go to the finer points."
    author_notes = (
        "The learner already knows the standard material. Skip definitions, go deep, and challenge them with "
        "difficult cases."
    )


class LessonShapes:
    """The registry. A fifth level would be one new class and one line here."""

    _SHAPES: ClassVar[tuple[LessonShape, ...]] = (BeginnerShape(), FoundationShape(), ProficientShape(), ExpertShape())
    assert all(shape.page_keys == PAGE_KEYS for shape in _SHAPES)

    @classmethod
    def all(cls) -> tuple[LessonShape, ...]:
        return cls._SHAPES

    @classmethod
    def for_level(cls, level: Any) -> LessonShape:
        wanted = Level.parse(level)
        return next(shape for shape in cls._SHAPES if shape.level is wanted)

    @classmethod
    def of(cls, document: dict) -> LessonShape:
        """The shape of a stored assessment or plan, reading its level by the scheme it was written under."""
        return cls.for_level(LevelScheme.level_of(document))

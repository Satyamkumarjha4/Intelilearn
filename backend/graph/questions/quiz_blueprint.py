"""The cells of a quick quiz (plan §6.6): each question's type, difficulty, marks and the lesson it is about.

Like a lesson test's blueprint, it is decided in code, so what the model is asked for does not depend on the model. A
quiz from several lessons gives each lesson its share of cells together, with the difficulty mix of that lesson's own
level (plan D18, D21), so a batch of five covers one or two lessons and never needs the summaries of the others.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from ..difficulty_mix import DifficultyMix
from ..levels import Level
from .blueprint import Cell
from .marks import MarksPolicy
from .registry import QuestionTypes


@dataclass(frozen=True)
class SourcePart:
    """One lesson's part of a quiz: its key, the level its questions are written at and how many of them there are. A
    quiz from a topic has one part with no key."""

    key: str
    level: Level
    share: int


class QuizBlueprint:
    KIND = "quiz"

    def __init__(self, parts: tuple[SourcePart, ...], types: tuple[str, ...]):
        if not parts:
            raise ValueError("A quiz needs at least one source.")
        if not types or any(kind not in QuestionTypes.OFFERED for kind in types):
            raise ValueError(f"A quiz asks for some of {', '.join(QuestionTypes.OFFERED)}, got {list(types)!r}.")
        for part in parts:
            if type(part.share) is not int or part.share < 1:
                raise ValueError(f"Every source needs a share of at least one question, got {part.share!r}.")
        self.parts, self.types = tuple(parts), tuple(types)
        self.cells = self._cells()

    @classmethod
    def for_topic(cls, count: int, types: Sequence[str], level: Level) -> "QuizBlueprint":
        return cls((SourcePart("", level, count),), tuple(types))

    @classmethod
    def for_lessons(cls, parts: Sequence[SourcePart], types: Sequence[str]) -> "QuizBlueprint":
        return cls(tuple(parts), tuple(types))

    def _cells(self) -> tuple[Cell, ...]:
        cells: list[Cell] = []
        for part in self.parts:
            for difficulty in DifficultyMix.for_level(part.level, part.share).ordered():
                kind = self.types[len(cells) % len(self.types)]  # the kinds picked are dealt out in turn
                cells.append(Cell(len(cells), kind, difficulty.value, MarksPolicy.marks(kind, difficulty), part.key))
        return tuple(cells)

    @property
    def total_marks(self) -> int:
        return sum(cell.marks for cell in self.cells)

    def missing(self, accepted: set[int]) -> tuple[Cell, ...]:
        """The cells no accepted question fills yet."""
        return tuple(cell for cell in self.cells if cell.index not in accepted)

    def to_json(self) -> dict:
        return {
            "kind": self.KIND,
            "types": list(self.types),
            "parts": [{"key": p.key, "level": p.level.value, "share": p.share} for p in self.parts],
            "total_marks": self.total_marks,
            "cells": [cell.as_dict() for cell in self.cells],
        }

    @classmethod
    def from_json(cls, data) -> "QuizBlueprint":
        """The blueprint that was stored. One whose cells are not what its parts and kinds give is refused."""
        if not isinstance(data, dict) or data.get("kind") != cls.KIND or not data.get("cells"):
            raise ValueError("Not a stored quiz blueprint")
        try:
            parts = tuple(SourcePart(p["key"], Level.parse(p["level"]), p["share"]) for p in data["parts"])
            blueprint = cls(parts, tuple(data["types"]))
        except (KeyError, TypeError) as exc:
            raise ValueError("Not a stored quiz blueprint") from exc
        stored = data["cells"]
        if len(stored) != len(blueprint.cells):
            raise ValueError("The stored cells are not the blueprint's cells: the number of cells differs")
        for cell, saved in zip(blueprint.cells, stored, strict=True):
            if wrong := [name for name, value in cell.as_dict().items() if saved.get(name) != value]:
                raise ValueError(
                    f"The stored cells are not the blueprint's cells: cell {cell.index} differs in {wrong[0]}"
                )
        return blueprint

    def __eq__(self, other) -> bool:
        return isinstance(other, QuizBlueprint) and (self.parts, self.types) == (other.parts, other.types)

    def __hash__(self) -> int:
        return hash((self.parts, self.types))

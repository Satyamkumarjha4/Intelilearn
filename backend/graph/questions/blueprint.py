"""The fixed ten cells of a lesson's test (docs/to_be_developed/modular-lessons-implementation-plan.md D15).

Every lesson, at every level, has the same test: ten objective questions, two for each difficulty. A cell is one
question's type and difficulty. The marks come from the marks table, so the total is the same for every attempt of a
lesson (20 for a quantitative topic, 18 for any other) and attempts can be compared.
"""

from dataclasses import dataclass

from .marks import MarksPolicy


@dataclass(frozen=True)
class Cell:
    index: int  # 0 to 9; the question written for it is "t{index + 1}"
    type: str
    difficulty: str
    marks: int
    source: str = ""  # a quiz made from lessons: the key of the lesson this question is about (else empty)

    @property
    def question_id(self) -> str:
        return f"t{self.index + 1}"

    def as_dict(self) -> dict:
        cell = {"index": self.index, "type": self.type, "difficulty": self.difficulty, "marks": self.marks}
        return {**cell, "source": self.source} if self.source else cell


class LessonTestBlueprint:
    """The cells of a lesson's test. Not a setting: changing it would make old and new attempts incomparable."""

    SIZE = 10

    #: (difficulty, the types of its two cells) for a quantitative topic and for any other topic
    QUANTITATIVE = (
        ("easy", ("mcq", "mcq")), ("basic", ("mcq", "msq")), ("standard", ("mcq", "numerical")),
        ("difficult", ("msq", "numerical")), ("expert", ("msq", "numerical")),
    )  # fmt: skip
    OTHER = (
        ("easy", ("mcq", "mcq")), ("basic", ("mcq", "msq")), ("standard", ("mcq", "msq")),
        ("difficult", ("msq", "mcq")), ("expert", ("msq", "mcq")),
    )  # fmt: skip

    def __init__(self, quantitative: bool, cells: tuple[Cell, ...]):
        self.quantitative = quantitative
        self.cells = cells

    @classmethod
    def for_topic(cls, quantitative: bool) -> "LessonTestBlueprint":
        table = cls.QUANTITATIVE if quantitative else cls.OTHER
        pairs = [(difficulty, kind) for difficulty, kinds in table for kind in kinds]
        cells = tuple(
            Cell(n, kind, difficulty, MarksPolicy.marks(kind, difficulty)) for n, (difficulty, kind) in enumerate(pairs)
        )
        return cls(quantitative, cells)

    @classmethod
    def for_old_test(cls, questions: list[dict] | None) -> "LessonTestBlueprint":
        """For a lesson made before the blueprint, which never said whether its topic was quantitative: it was, if its
        old test asked a numerical question."""
        return cls.for_topic(any(q.get("type") == "numerical" for q in questions or []))

    @property
    def total_marks(self) -> int:
        return sum(cell.marks for cell in self.cells)

    def missing(self, accepted: set[int]) -> tuple[Cell, ...]:
        """The cells no accepted question fills yet."""
        return tuple(cell for cell in self.cells if cell.index not in accepted)

    def to_json(self) -> dict:
        return {
            "quantitative": self.quantitative,
            "total_marks": self.total_marks,
            "cells": [cell.as_dict() for cell in self.cells],
        }

    @classmethod
    def from_json(cls, data) -> "LessonTestBlueprint":
        """The blueprint that was stored. One whose cells are not the table is refused: the table is code."""
        if not isinstance(data, dict) or not isinstance(data.get("quantitative"), bool) or not data.get("cells"):
            raise ValueError("Not a stored test blueprint")
        blueprint = cls.for_topic(data["quantitative"])
        if data["cells"] != [cell.as_dict() for cell in blueprint.cells]:
            raise ValueError("The stored cells are not the blueprint's cells")
        return blueprint

    def __eq__(self, other) -> bool:
        return isinstance(other, LessonTestBlueprint) and (self.quantitative, self.cells) == (
            other.quantitative,
            other.cells,
        )

    def __hash__(self) -> int:
        return hash((self.quantitative, self.cells))

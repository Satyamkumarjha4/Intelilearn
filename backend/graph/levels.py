"""Learner levels and question difficulties: pure value classes, no ORM and no I/O (docs/architecture/design.md §4.17).

`Level` is where a learner stands in a topic; `StarRating` is how they rate themselves; `Difficulty` is how hard a
question is. They are not wired into the flow yet: the lesson code still uses its own level and difficulty names.
"""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Level names stored before the rename, mapped by position. "beginner" was also an old name (it meant Foundation), so it
# is left out of the first map: the normal reader takes it as the new Beginner, and only `parse_legacy` reads it the
# old way.
_OLD_LEVELS = {"novice": "beginner", "intermediate": "proficient", "advanced": "expert"}
_OLD_LEVELS_BY_POSITION = {
    "novice": "beginner",
    "beginner": "foundation",
    "intermediate": "proficient",
    "advanced": "expert",
}


class RaterCategory(StrEnum):
    """How far a learner's starting point is from the middle: it decides which follow-up offers make sense."""

    LOW = "low"
    MID = "mid"
    HIGH = "high"

    @classmethod
    def of(cls, level: "Level") -> "RaterCategory":
        """Beginner is low and Expert is high, the rest mid. For stars this is exactly the spec's "at most 1.5" and
        "at least 4.5"; it also covers a level that a quiz found instead of a rating."""
        if level is Level.BEGINNER:
            return cls.LOW
        if level is Level.EXPERT:
            return cls.HIGH
        return cls.MID


class Level(StrEnum):
    BEGINNER = "beginner"
    FOUNDATION = "foundation"
    PROFICIENT = "proficient"
    EXPERT = "expert"

    @classmethod
    def parse(cls, raw: Any) -> "Level":
        """A level from its name in any case, or from an old name that is unambiguous (not "beginner")."""
        name = cls._name(raw)
        return cls(_OLD_LEVELS.get(name, name))

    @classmethod
    def parse_legacy(cls, raw: Any) -> "Level":
        """For data known to predate the rename (checkpointed graph state), where "beginner" meant Foundation."""
        name = cls._name(raw)
        return cls(_OLD_LEVELS_BY_POSITION.get(name, name))

    @classmethod
    def _name(cls, raw: Any) -> str:
        if isinstance(raw, cls):
            return raw.value
        if not isinstance(raw, str):
            raise ValueError(f"Not a level: {raw!r}")
        name = raw.strip().lower()
        if name not in cls._value2member_map_ and name not in _OLD_LEVELS_BY_POSITION:
            raise ValueError(f"Unknown level: {raw!r}")
        return name

    def shifted(self, by: int) -> "Level":
        """The level `by` steps up (or down when negative), stopping at Beginner and Expert."""
        order = list(type(self))
        return order[max(0, min(len(order) - 1, order.index(self) + by))]

    @property
    def label(self) -> str:
        return self.value.title()


@dataclass(frozen=True)
class StarRating:
    """A self-rating of 0.5 to 5 stars in half-star steps, stored as whole halves (1 to 10) so it is never a float."""

    halves: int

    def __post_init__(self) -> None:
        if type(self.halves) is not int or not 1 <= self.halves <= 10:
            raise ValueError(f"A star rating is 1 to 10 halves, got {self.halves!r}")

    @classmethod
    def from_stars(cls, stars: Any) -> "StarRating":
        if isinstance(stars, bool) or not isinstance(stars, (int, float)) or not math.isfinite(stars):
            raise ValueError(f"Not a star rating: {stars!r}")
        halves = stars * 2
        if halves != int(halves):
            raise ValueError(f"Stars go in steps of half a star, got {stars!r}")
        return cls(int(halves))

    @property
    def stars(self) -> float:
        """For display only."""
        return self.halves / 2

    def level(self) -> Level:
        """0.5 to 1.5 Beginner, 2 to 3.5 Foundation, 4 Proficient, 4.5 to 5 Expert."""
        if self.halves <= 3:
            return Level.BEGINNER
        if self.halves <= 7:
            return Level.FOUNDATION
        if self.halves == 8:
            return Level.PROFICIENT
        return Level.EXPERT

    def rater_category(self) -> RaterCategory:
        return RaterCategory.of(self.level())


_OLD_DIFFICULTIES = {"medium": "standard", "hard": "difficult"}


class LevelScheme:
    """Which level names a stored document uses. The first scheme had novice, beginner, intermediate and advanced; the
    second has beginner, foundation, proficient and expert, and "beginner" is in both with different meanings. A
    document written under the second scheme carries `level_scheme: 2`; one without it is legacy, however it got here
    (a database row from before the rename, a graph checkpoint that was never rewritten)."""

    KEY = "level_scheme"
    CURRENT = 2

    @classmethod
    def stamp(cls, document: dict) -> dict:
        """A copy that says it uses the current names."""
        return {**document, cls.KEY: cls.CURRENT}

    @classmethod
    def level_of(cls, document: dict) -> Level:
        """The document's `level`, read the way it was written."""
        raw = document.get("level")
        return Level.parse(raw) if document.get(cls.KEY) == cls.CURRENT else Level.parse_legacy(raw)

    @classmethod
    def upgraded(cls, document: dict) -> dict:
        """The document with its level in the current names and the marker; a current one comes back as it is."""
        if document.get(cls.KEY) == cls.CURRENT:
            return document
        return cls.stamp({**document, "level": cls.level_of(document).value})


class MarkTier(StrEnum):
    """Which column of the marks table a question is in."""

    NORMAL = "normal"
    DIFFICULT = "difficult"


class Difficulty(StrEnum):
    """Five levels, easiest first. The first three are the normal mark tier, the last two the difficult one."""

    EASY = "easy"
    BASIC = "basic"
    STANDARD = "standard"
    DIFFICULT = "difficult"
    EXPERT = "expert"

    @classmethod
    def parse(cls, raw: Any) -> "Difficulty":
        """A difficulty from its name in any case, or from the old "medium" (standard) and "hard" (difficult)."""
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, str):
            raise ValueError(f"Not a difficulty: {raw!r}")
        name = raw.strip().lower()
        try:
            return cls(_OLD_DIFFICULTIES.get(name, name))
        except ValueError:
            raise ValueError(f"Unknown difficulty: {raw!r}") from None

    @property
    def tier(self) -> MarkTier:
        return (
            MarkTier.NORMAL if self in (Difficulty.EASY, Difficulty.BASIC, Difficulty.STANDARD) else MarkTier.DIFFICULT
        )


class BandDifficulty:
    """The bridge between the diagnostic's five bands and the five difficulties.

    The two vocabularies overlap in words but not in meaning (the band `hard` is the difficulty `expert`), and nothing
    renames the bands, so the map is explicit and one to one.
    """

    _BAND_TO_DIFFICULTY = {
        "basic": Difficulty.EASY,
        "easy_moderate": Difficulty.BASIC,
        "moderate": Difficulty.STANDARD,
        "moderate_hard": Difficulty.DIFFICULT,
        "hard": Difficulty.EXPERT,
    }

    @classmethod
    def of(cls, band: Any) -> Difficulty:
        try:
            return cls._BAND_TO_DIFFICULTY[band]
        except (KeyError, TypeError):
            raise ValueError(f"Unknown diagnostic band: {band!r}") from None

    @classmethod
    def band_of(cls, difficulty: Difficulty) -> str:
        for band, mapped in cls._BAND_TO_DIFFICULTY.items():
            if mapped is difficulty:
                return band
        raise ValueError(f"No diagnostic band for {difficulty!r}")

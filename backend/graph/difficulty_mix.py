"""How many questions of each difficulty a quick quiz asks, for a learner's level (plan D21). Pure.

The shares are percentages and a quiz has 5 to 30 questions, so a count that does not divide evenly has to land
somewhere. Largest-remainder rounding makes every count add up exactly, and a tie goes to the easier difficulty, so a
rounding choice never makes a quiz harder than the table says. All the arithmetic is on whole numbers.
"""

from dataclasses import dataclass
from typing import Any, ClassVar

from .levels import Difficulty, Level


@dataclass(frozen=True)
class DifficultyMix:
    """The number of questions of each difficulty."""

    counts: dict[Difficulty, int]

    #: the default share of each difficulty in percent (easy, basic, standard, difficult, expert), by level. A constant:
    #: changing it would make quizzes of the same level incomparable
    SHARES: ClassVar[dict[Level, dict[Difficulty, int]]] = {
        level: dict(zip(Difficulty, shares, strict=True))
        for level, shares in {
            Level.BEGINNER: (30, 40, 20, 10, 0),
            Level.FOUNDATION: (10, 30, 40, 20, 0),
            Level.PROFICIENT: (0, 10, 40, 30, 20),
            Level.EXPERT: (0, 0, 20, 40, 40),
        }.items()
    }

    @classmethod
    def for_level(cls, level: Any, count: Any) -> "DifficultyMix":
        if type(count) is not int or count < 0:
            raise ValueError(f"A question count is a whole number from 0 up, got {count!r}")
        shares = cls.SHARES[Level.parse(level)]
        floors = {d: share * count // 100 for d, share in shares.items()}
        remainders = {d: share * count % 100 for d, share in shares.items()}
        spare = count - sum(floors.values())
        # the largest remainder first; equal remainders go to the easier difficulty (Difficulty is in order)
        by_remainder = sorted(Difficulty, key=lambda d: (-remainders[d], list(Difficulty).index(d)))
        for difficulty in by_remainder[:spare]:
            floors[difficulty] += 1
        return cls(floors)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def ordered(self) -> list[Difficulty]:
        """The difficulties easiest first, each as many times as it was asked for."""
        return [difficulty for difficulty in Difficulty for _ in range(self.counts[difficulty])]

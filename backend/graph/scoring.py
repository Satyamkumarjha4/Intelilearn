"""Score bands: Fail, Normal or Excellent from marks. Pure, and integers only (docs/architecture/design.md §4.17).

Percentages are never computed as floats. 90% of 20 marks is 18, but `0.9 * 20` need not be exactly 18.0; comparing
`awarded * 100` with `percent * available` is exact.
"""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class Thresholds:
    """Whole percents: under `fail_below` is Fail, over `excellent_above` is Excellent. Both edges are Normal."""

    fail_below: int = 30
    excellent_above: int = 90

    def __post_init__(self) -> None:
        for value in (self.fail_below, self.excellent_above):
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError(f"A threshold is a whole percent from 0 to 100, got {value!r}")
        if self.fail_below > self.excellent_above:
            raise ValueError("The fail threshold cannot be above the excellent threshold")


class ScoreBand(StrEnum):
    FAIL = "fail"
    NORMAL = "normal"
    EXCELLENT = "excellent"

    @classmethod
    def of(cls, awarded: int, available: int, thresholds: Thresholds | None = None) -> "ScoreBand":
        thresholds = thresholds or Thresholds()
        for marks in (awarded, available):
            if type(marks) is not int:
                raise ValueError(f"Marks are whole numbers, got {marks!r}")
        if available <= 0:
            raise ValueError("A band needs at least one mark available")
        if not 0 <= awarded <= available:
            raise ValueError(f"Awarded marks must be between 0 and {available}, got {awarded}")
        if awarded * 100 < thresholds.fail_below * available:
            return cls.FAIL
        if awarded * 100 > thresholds.excellent_above * available:
            return cls.EXCELLENT
        return cls.NORMAL

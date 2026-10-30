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


@dataclass(frozen=True)
class TrendPoint:
    attempt_no: int
    awarded: int
    available: int
    percent: int
    delta_previous: int | None  # in percentage points; none for the first attempt
    delta_best: int | None  # against the best of the earlier attempts; none for the first attempt


@dataclass(frozen=True)
class Trend:
    series: tuple[TrendPoint, ...]
    best_attempt_no: int | None  # the earliest attempt that reached the highest percent


class AttemptTrend:
    """The graded attempts of a lesson in order, each with its change since the previous attempt and since the best
    earlier one. Percents are compared rather than marks, because the first attempt of a lesson made before the fixed
    test may have another total."""

    def of(self, attempts: list[dict]) -> Trend:
        """`attempts`: dicts with `attempt_no`, `awarded` and `available`, in any order."""
        points: list[TrendPoint] = []
        for attempt in sorted(attempts, key=lambda a: a["attempt_no"]):
            percent = self.percent(attempt["awarded"], attempt["available"])
            previous = points[-1].percent if points else None
            best = max((p.percent for p in points), default=None)
            points.append(
                TrendPoint(
                    attempt["attempt_no"], attempt["awarded"], attempt["available"], percent,
                    None if previous is None else percent - previous,
                    None if best is None else percent - best,
                )
            )  # fmt: skip
        top = max((p.percent for p in points), default=None)
        best_no = next((p.attempt_no for p in points if p.percent == top), None)
        return Trend(tuple(points), best_no)

    @staticmethod
    def percent(awarded: int, available: int) -> int:
        return round(100 * awarded / available) if available else 0

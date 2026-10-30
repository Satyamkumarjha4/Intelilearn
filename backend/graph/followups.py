"""What a finished attempt leads to: a follow-up offer, decided by a pure rule (docs/architecture/design.md §4.21).

The rule is the spec's (section 3.3). A pop-up appears only when the result contradicts the learner's own level, because
Socra must not tell people they are wrong about it: a learner who rated low and failed rated themselves correctly, and
one who rated high and excelled did too. Everything the rule needs is handed in, so it has no database and is
table-tested; `lessons/followups.py` gathers the facts.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .levels import RaterCategory
from .scoring import ScoreBand, Thresholds


@dataclass(frozen=True)
class Offer:
    """What the learner is offered, stored on the attempt as JSON.

    `kind`: `foundation`, `advanced` or `inline_suggestion` (the small note under a low rater's failed result).
    `action`: `generate` (make the lesson), `revisit` (a Foundation lesson that exists), `open` (an Advanced lesson that
    exists) or `revisit_or_related` (the inline note: look at the lesson again, or try a related one).
    """

    kind: str
    action: str
    lesson_id: Any = None

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "action": self.action,
            "lesson_id": None if self.lesson_id is None else str(self.lesson_id),
        }

    @classmethod
    def from_json(cls, data: dict) -> "Offer":
        return cls(data["kind"], data["action"], data.get("lesson_id"))


class Passes:
    """Whether a learner has passed: scored at or above the Fail line, judged on whole marks."""

    @staticmethod
    def once(scores: Iterable[tuple[int, int]], fail_below: int = Thresholds().fail_below) -> bool:
        """`scores` are (awarded, available) of the learner's earlier graded attempts."""
        return any(available > 0 and awarded * 100 >= fail_below * available for awarded, available in scores)


class FollowupPolicy:
    def decide(
        self,
        band: ScoreBand,
        rater: RaterCategory,
        passed_once: bool,
        existing: Mapping[str, Any],
        *,
        blank: bool = False,
    ) -> Offer | None:
        """`passed_once`: an earlier attempt scored at or above the Fail line. `existing`: the lessons already made from
        this one, by level (`foundation`, `advanced`) → id. `blank`: every answer was blank, which scores 0 and never
        gets
        an offer, so an empty submit cannot be used to collect lessons."""
        if band not in tuple(ScoreBand):
            raise ValueError(f"Not a score band: {band!r}")
        if blank:
            return None
        if band is ScoreBand.FAIL:
            return self._fail(rater, passed_once, existing)
        if band is ScoreBand.EXCELLENT:
            return self._excellent(rater, existing)
        return None

    @staticmethod
    def _fail(rater: RaterCategory, passed_once: bool, existing: Mapping[str, Any]) -> Offer | None:
        if rater is RaterCategory.LOW:
            return Offer("inline_suggestion", "revisit_or_related")
        if passed_once:
            return None
        found = existing.get("foundation")
        return Offer("foundation", "revisit", found) if found else Offer("foundation", "generate")

    @staticmethod
    def _excellent(rater: RaterCategory, existing: Mapping[str, Any]) -> Offer | None:
        if rater is RaterCategory.HIGH:
            return None
        found = existing.get("advanced")
        return Offer("advanced", "open", found) if found else Offer("advanced", "generate")

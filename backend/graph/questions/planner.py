"""Splits the cells of a test into the batches a model writes (docs/to_be_developed/..., §6.6)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .blueprint import Cell

SUBJECTIVE = ("short_answer", "long_answer")


@dataclass(frozen=True)
class Batch:
    id: str  # "b{round}-{n}": a second round for missing cells never reuses an id
    cells: tuple[Cell, ...]


class BatchPlanner:
    """Gives each batch an explicit list of cells, so the union is correct by construction whatever the model does.

    The subjective cap keeps a quiz from being all long answers by accident: a batch holds at most `max_long` long and
    `max_short` short answers. It is off when the learner picked only short or long answers (it would block their
    choice) and can be switched off (`capped=False`)."""

    MIN_SIZE, MAX_SIZE = 5, 10

    def __init__(self, size: int = 5, max_long: int = 1, max_short: int = 2, capped: bool = True):
        self.size = min(max(size, self.MIN_SIZE), self.MAX_SIZE)
        self.max_long = max_long
        self.max_short = max_short
        self.capped = capped

    @classmethod
    def from_settings(cls, settings: dict, capped: bool = True) -> "BatchPlanner":
        return cls(
            size=settings.get("question_batch_size", 5),
            max_long=settings.get("batch_max_long", 1),
            max_short=settings.get("batch_max_short", 2),
            capped=capped,
        )

    @staticmethod
    def cap_applies(picked_types: Iterable[str]) -> bool:
        """False when the learner picked only short and long answers, since a cap would stop them getting what they
        asked for."""
        picked = set(picked_types)
        return not (picked and picked <= set(SUBJECTIVE))

    def plan(self, cells: Sequence[Cell], round_no: int = 1) -> list[Batch]:
        """Each cell goes to the first batch with room for it (size, and the cap), in order."""
        groups: list[list[Cell]] = []
        for cell in cells:
            for group in groups:
                if self._fits(group, cell):
                    group.append(cell)
                    break
            else:
                groups.append([cell])
        return [Batch(f"b{round_no}-{n}", tuple(group)) for n, group in enumerate(groups, start=1)]

    def _fits(self, group: list[Cell], cell: Cell) -> bool:
        if len(group) >= self.size:
            return False
        if not self.capped:
            return True
        limit = {"long_answer": self.max_long, "short_answer": self.max_short}.get(cell.type)
        return limit is None or sum(1 for c in group if c.type == cell.type) < limit

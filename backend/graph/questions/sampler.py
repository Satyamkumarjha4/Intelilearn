"""Spends questions that were written but never served before anything new is generated."""

import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from .blueprint import Cell


@dataclass
class Draw:
    picks: dict[int, dict] = field(default_factory=dict)  # cell index → the question that fills it
    empty: tuple[Cell, ...] = ()  # the cells nothing could fill, in order


class BlueprintSampler:
    """Draws, for each cell, an unserved question of its type and difficulty. Never a retired one, and never the same
    question twice. The same seed (the lesson and the attempt number) draws the same questions."""

    def draw(self, cells: Sequence[Cell], candidates: list[dict], seed: str) -> Draw:
        rng = random.Random(seed)
        available: dict[tuple[str, str], list[dict]] = {}
        for candidate in sorted((c for c in candidates if not c.get("retired")), key=lambda c: str(c["id"])):
            available.setdefault((candidate["type"], candidate["difficulty"]), []).append(candidate)
        draw = Draw()
        empty = []
        for cell in cells:
            pool = available.get((cell.type, cell.difficulty), [])
            if pool:
                draw.picks[cell.index] = pool.pop(rng.randrange(len(pool)))
            else:
                empty.append(cell)
        draw.empty = tuple(empty)
        return draw

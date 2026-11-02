"""Which concepts a question written for a lesson may name (plan §9.6, R18). Pure.

A weak concept in a quiz result is linked to the page that teaches it by looking it up in the lesson's concept index.
Free text from the model would match only by luck, so a question about a lesson must name one of that lesson's concepts:
the model is told the list, a near-miss in case or spacing is written with the lesson's own spelling, and anything else
is reported so the batch is written again.
"""

from collections.abc import Sequence

from ..normal import Normal
from .blueprint import Cell


class QuestionConcepts:
    @staticmethod
    def allowed(data: dict, cells: Sequence[Cell]) -> list[list[str] | None]:
        """For each cell, the concepts its question may name, or None when anything goes (a topic quiz). A lesson's
        test, or a retake of it, draws on the whole plan; a quiz from lessons on the concepts that fit the summary of
        the cell's own lesson."""
        if data.get("quiz"):
            sources = data["quiz"].get("sources") or {}
            return [(sources.get(cell.source) or {}).get("concepts") or None for cell in cells]
        if data.get("plan"):
            names = QuestionConcepts.outline(data["plan"])
            return [list(names) or None for _ in cells]
        return [None for _ in cells]

    @staticmethod
    def outline(plan: dict) -> list[str]:
        """Every concept of the plan's outline, once, in teaching order."""
        names = (str(item.get("concept", "")).strip() for page in plan.get("pages") or [] for item in page["outline"])
        return list(dict.fromkeys(name for name in names if name))

    @staticmethod
    def canonicalise(questions: list[dict], allowed: Sequence[Sequence[str] | None]) -> None:
        """A concept that differs from an allowed one only in case or spacing is written the way the lesson spells it,
        in place."""
        for question, names in zip(questions, allowed, strict=False):
            by_norm = {Normal.text(name): name for name in names or []}
            question["concept"] = by_norm.get(Normal.text(str(question.get("concept", ""))), question["concept"])

    @staticmethod
    def problems(questions: list[dict], allowed: Sequence[Sequence[str] | None]) -> list[str]:
        found = []
        for question, names in zip(questions, allowed, strict=False):
            if names and Normal.text(str(question.get("concept", ""))) not in {Normal.text(n) for n in names}:
                found.append(
                    f'Question {question["id"]}: the concept "{question.get("concept", "")}" must be one of: '
                    f"{'; '.join(names)}."
                )
        return found

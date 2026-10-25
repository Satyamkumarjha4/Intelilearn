"""The mastery path: cheat sheet, revision sheet and practice sheet."""

from ..schemas.lesson import DIFFICULTIES
from .base import LatexChecker, LatexRules, TextRules
from .questions import QuestionRules


class StudyMaterialValidator:
    def __init__(self, latex: LatexChecker | None = None):
        self.latex = LatexRules(latex)

    def validate(self, content: dict, *, kind: str, concepts: list[str]) -> list[str]:
        checks = {"cheat_sheet": self._cheat, "revision_sheet": self._revision, "practice_sheet": self._practice}
        if kind not in checks:
            return [f"Unknown study material kind {kind!r}."]
        problems, texts = checks[kind](content)
        missing = [c for c in concepts if not any(TextRules.mentions(t, c) for t in texts)]
        if missing and len(missing) > len(concepts) // 3:
            problems.append("Cover the topic's key concepts; these are missing: " + "; ".join(missing))
        return problems

    def _cheat(self, content: dict) -> tuple[list[str], list[str]]:
        problems, texts = [], []
        items = [item for section in content["sections"] for item in section["items"]]
        if len(content["sections"]) < 2:
            problems.append("Use at least 2 sections.")
        if len(items) < 6:
            problems.append(f"A cheat sheet needs at least 6 items; it has {len(items)}.")
        if len(items) > 40:
            problems.append("Too long for a cheat sheet: keep it to at most 40 items.")
        for item in items:
            if item["kind"] == "formula" and not item["formula"]:
                problems.append(f'"{item["label"]}" is a formula item but has no formula.')
            texts += [item["content"], item["when_to_use"]]
        expressions = [item["formula"] for item in items] + [v["symbol"] for i in items for v in i["variables"]]
        problems += self.latex.problems(expressions + [m for t in texts for m in TextRules.math_in(t)])
        return problems, texts + [item["label"] for item in items]

    def _revision(self, content: dict) -> tuple[list[str], list[str]]:
        problems, texts = [], []
        subtopics = content["subtopics"]
        if len(subtopics) < 4:
            problems.append(f"Cover every subtopic: at least 4 are needed; there are {len(subtopics)}.")
        for sub in subtopics:
            if len(sub["summary"]) < 150:
                problems.append(f'Subtopic "{sub["title"]}" needs a fuller summary (at least a paragraph).')
            if len(sub["key_points"]) < 3:
                problems.append(f'Subtopic "{sub["title"]}" needs at least 3 key points.')
            texts += [sub["title"], sub["summary"], *sub["key_points"], *sub["common_mistakes"]]
            texts += [part for ex in sub["worked_examples"] for part in (ex["problem"], ex["solution"])]
        problems += self.latex.problems([m for t in texts for m in TextRules.math_in(t)])
        return problems, texts

    def _practice(self, content: dict) -> tuple[list[str], list[str]]:
        problems = []
        questions = content["questions"]
        if not 15 <= len(questions) <= 25:
            problems.append(f"A practice sheet has 15-25 questions; it has {len(questions)}.")
        order = [DIFFICULTIES.index(q["difficulty"]) for q in questions]
        if order != sorted(order):
            problems.append("Order the questions from easy to hard.")
        if len({q["type"] for q in questions}) < 3:
            problems.append("Mix at least 3 question types.")
        problems += QuestionRules.problems(questions)
        problems += self.latex.problems([m for q in questions for m in TextRules.math_in(q["question"])])
        return problems, [q["question"] for q in questions] + [q["concept"] for q in questions]

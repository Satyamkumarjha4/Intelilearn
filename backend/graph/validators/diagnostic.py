"""Stage A: the diagnostic bundle (diagnostic quiz + prerequisite quiz) and the assessment that follows."""

from collections import Counter
from collections.abc import Callable, Iterable

from ..schemas.diagnostic import BANDS
from .base import LatexChecker, LatexRules, TextRules

norm = TextRules.norm


class DiagnosticValidator:
    def __init__(self, latex: LatexChecker | None = None):
        self.latex = LatexRules(latex)

    def validate(self, bundle: dict, *, settings: dict) -> list[str]:
        per_band = settings.get("diagnostic_questions_per_band", 2)
        questions = bundle["diagnostic"]
        problems = self._counts(questions, per_band)
        if dupes := TextRules.duplicates(q["id"] for q in questions):
            problems.append(f"Question ids must be unique (repeated: {', '.join(dupes)}).")
        if dupes := TextRules.duplicates(norm(q["concept"]) for q in questions):
            problems.append(f"Each question must probe a different concept (repeated: {', '.join(dupes)}).")
        for q in questions:
            problems += TextRules.option_problems(f"Question {q['id']}", q["options"])
        problems += self._independence(questions)
        problems += self._prerequisites(bundle, settings.get("prerequisite_question_count", 5))
        return problems + self._latex(bundle)

    @staticmethod
    def _counts(questions: list[dict], per_band: int) -> list[str]:
        problems = []
        expected = per_band * len(BANDS)
        if len(questions) != expected:
            problems.append(
                f"The diagnostic must have exactly {expected} questions ({per_band} per band); it has {len(questions)}."
            )
        bands = Counter(q["band"] for q in questions)
        for band in BANDS:
            if bands.get(band, 0) != per_band:
                problems.append(f'Band "{band}" must have exactly {per_band} questions; it has {bands.get(band, 0)}.')
        return problems

    @staticmethod
    def _independence(questions: list[dict]) -> list[str]:
        """No question may give away another's answer."""
        problems = []
        for q in questions:
            answer = norm(q["options"][q["correct_index"]])
            if len(answer) < 6 or answer.replace(" ", "").isdigit():
                continue  # short answers ("3", "O(n)") appear in text by coincidence
            for other in questions:
                if other is not q and answer in norm(other["question"]):
                    problems.append(
                        f'Question {other["id"]} reveals the answer to {q["id"]} ("{answer}"); '
                        "questions must be independent."
                    )
        return problems

    @staticmethod
    def _prerequisites(bundle: dict, expected_count: int) -> list[str]:
        problems = []
        prerequisites, questions = bundle["prerequisites"], bundle["prerequisite_questions"]
        if len(prerequisites) != expected_count:
            problems.append(f"There must be exactly {expected_count} prerequisites; there are {len(prerequisites)}.")
        if len(questions) != len(prerequisites):
            problems.append("There must be exactly one prerequisite question per prerequisite.")
        names = [norm(p["name"]) for p in prerequisites]
        if dupes := TextRules.duplicates(names):
            problems.append(f"Prerequisites must be different (repeated: {', '.join(dupes)}).")
        mapped = Counter(norm(q["prerequisite"]) for q in questions)
        for q in questions:
            if norm(q["prerequisite"]) not in names:
                problems.append(
                    f'Prerequisite question {q["id"]} refers to "{q["prerequisite"]}", which is not one of '
                    "the prerequisites; use the exact name."
                )
            problems += TextRules.option_problems(f"Prerequisite question {q['id']}", q["options"])
        for name, prerequisite in zip(names, prerequisites, strict=False):
            if mapped.get(name, 0) != 1:
                problems.append(f'Prerequisite "{prerequisite["name"]}" needs exactly one question.')
        ids = [q["id"] for q in bundle["diagnostic"]] + [q["id"] for q in questions]
        if dupes := TextRules.duplicates(ids):
            problems.append(f"Ids must be unique across both quizzes (repeated: {', '.join(dupes)}).")
        return problems

    def _latex(self, bundle: dict) -> list[str]:
        everything = bundle["diagnostic"] + bundle["prerequisite_questions"]
        texts = [q["question"] for q in everything] + [o for q in everything for o in q["options"]]
        return self.latex.problems([m for t in texts for m in TextRules.math_in(t)])


class DiagnosticReviewValidator:
    """The optional `diagnostic.review` judge, as a validator: independence and band calibration.

    `reviewer` takes the bundle and returns (question_id, problem) pairs; the node builds one that calls the gateway.
    """

    def __init__(self, reviewer: Callable[[dict], Iterable[tuple[str, str]]]):
        self.reviewer = reviewer

    def validate(self, bundle: dict, **context) -> list[str]:
        return [f"Question {question_id}: {problem}" for question_id, problem in self.reviewer(bundle)]


class AssessmentGuard:
    """The LLM may explain the gaps but may not change which prerequisites are covered."""

    def apply(self, assessment: dict, prerequisites_to_cover: list[dict]) -> dict:
        return {**assessment, "prerequisites_to_cover": [p["name"] for p in prerequisites_to_cover]}

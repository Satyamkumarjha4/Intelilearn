"""Quiz grading and routing: pure functions shared by the API (instant score) and the graph (routing).

Answers are {question_id: option_index | "dont_know"}. "I don't know" scores as wrong: it keeps guessing
from inflating the learner's level (10 four-option questions give ~2.5 correct by chance).
"""

from typing import Literal, TypedDict

from .schemas.diagnostic import BANDS

DONT_KNOW = "dont_know"
Route = Literal["prerequisite", "lesson", "mastery"]


class QuizResult(TypedDict):
    correct: int
    total: int
    dont_know: int
    by_band: dict[str, list[int]]  # band → [correct, total] (diagnostic only)
    by_concept: dict[str, bool]  # concept (or prerequisite name) → answered correctly
    per_question: dict[str, bool]
    highest_band_fully_correct: str | None
    consistent: bool  # False when harder bands score clearly better than easier ones (probably guessing)


class AnswerError(ValueError):
    """The answers don't fit the quiz (missing, unknown, or out-of-range)."""


def check_answers(questions: list[dict], answers: dict) -> dict[str, int | str]:
    ids = [q["id"] for q in questions]
    missing = [qid for qid in ids if qid not in answers]
    if missing:
        raise AnswerError(f"Answer every question (missing: {', '.join(missing)}).")
    unknown = sorted(set(answers) - set(ids))
    if unknown:
        raise AnswerError(f"Unknown question ids: {', '.join(unknown)}.")
    clean = {}
    for question in questions:
        value = answers[question["id"]]
        if value == DONT_KNOW:
            clean[question["id"]] = DONT_KNOW
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(question["options"]):
            raise AnswerError(f"Answer for {question['id']} must be an option index or {DONT_KNOW!r}.")
        clean[question["id"]] = value
    return clean


def grade_quiz(questions: list[dict], answers: dict) -> QuizResult:
    answers = check_answers(questions, answers)
    per_question = {q["id"]: answers[q["id"]] == q["correct_index"] for q in questions}
    by_band: dict[str, list[int]] = {}
    for question in questions:
        if band := question.get("band"):
            counts = by_band.setdefault(band, [0, 0])
            counts[0] += per_question[question["id"]]
            counts[1] += 1
    by_band = {band: by_band[band] for band in BANDS if band in by_band}
    by_concept = {q.get("concept") or q.get("prerequisite") or q["id"]: per_question[q["id"]] for q in questions}

    fully_correct = [band for band, (right, total) in by_band.items() if right == total]
    return QuizResult(
        correct=sum(per_question.values()),
        total=len(questions),
        dont_know=sum(1 for value in answers.values() if value == DONT_KNOW),
        by_band=by_band,
        by_concept=by_concept,
        per_question=per_question,
        highest_band_fully_correct=fully_correct[-1] if fully_correct else None,
        consistent=_consistent(by_band),
    )


def _consistent(by_band: dict[str, list[int]]) -> bool:
    """A harder band fully right while an easier band is at most half right suggests lucky guesses."""
    fractions = [right / total for right, total in by_band.values() if total]
    return not any(
        fractions[harder] == 1 and fractions[easier] <= 0.5
        for easier in range(len(fractions))
        for harder in range(easier + 1, len(fractions))
    )


def route_for(result: QuizResult, settings: dict) -> Route:
    hard_right, hard_total = result["by_band"].get("hard", [0, 0])
    all_hard = hard_total > 0 and hard_right == hard_total
    if settings.get("mastery_requires_all_correct", True):
        mastered = result["correct"] == result["total"]
    else:
        mastered = all_hard and result["correct"] >= result["total"] - 1
    if mastered:
        return "mastery"
    if result["correct"] <= settings.get("prereq_trigger_max_correct", 2):
        return "prerequisite"
    return "lesson"


def prerequisites_to_cover(prerequisites: list[dict], questions: list[dict], result: QuizResult) -> list[dict]:
    """0/5 → all prerequisites, 5/5 → none, partial → only the missed ones (in the original order)."""
    missed = {q["prerequisite"].strip().lower() for q in questions if not result["per_question"][q["id"]]}
    return [p for p in prerequisites if p["name"].strip().lower() in missed]


def summary(result: QuizResult, route: Route | None = None) -> dict:
    """What the learner sees right after submitting (QuizResultSummary in docs/api.md)."""
    data = {
        "correct": result["correct"],
        "total": result["total"],
        "dont_know": result["dont_know"],
        "by_band": result["by_band"],
    }
    if route:
        data["route"] = route
    return data

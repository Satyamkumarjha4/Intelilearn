"""Quiz grading and routing, shared by the API (instant score) and the graph (routing), so both always agree.

Answers are {question_id: option_index | "dont_know"}. "I don't know" scores as wrong: it keeps guessing
from inflating the learner's level (10 four-option questions give ~2.5 correct by chance).
"""

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .schemas.diagnostic import BANDS

DONT_KNOW = "dont_know"
Route = Literal["prerequisite", "lesson", "mastery"]


class AnswerError(ValueError):
    """The answers don't fit the quiz (missing, unknown, or out-of-range)."""


@dataclass(frozen=True)
class QuizResult:
    correct: int
    total: int
    dont_know: int
    by_band: dict[str, list[int]]  # band → [correct, total] (diagnostic only)
    by_concept: dict[str, bool]  # concept (or prerequisite name) → answered correctly
    per_question: dict[str, bool]
    highest_band_fully_correct: str | None
    consistent: bool = field(default=True)  # False when harder bands score clearly better than easier ones

    def as_dict(self) -> dict:
        """Plain JSON, as stored in graph state and on `QuizAttempt.result`."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "QuizResult":
        return cls(**data)

    def summary(self, route: Route | None = None) -> dict:
        """What the learner sees right after submitting (QuizResultSummary in docs/api.md)."""
        data = {"correct": self.correct, "total": self.total, "dont_know": self.dont_know, "by_band": self.by_band}
        if route:
            data["route"] = route
        return data


class QuizGrader:
    def check_answers(self, questions: list[dict], answers: dict) -> dict[str, int | str]:
        """The answers cleaned up (one per question), or an AnswerError saying what is wrong."""
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
            elif isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(question["options"]):
                raise AnswerError(f"Answer for {question['id']} must be an option index or {DONT_KNOW!r}.")
            else:
                clean[question["id"]] = value
        return clean

    def grade(self, questions: list[dict], answers: dict) -> QuizResult:
        answers = self.check_answers(questions, answers)
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
            consistent=self._consistent(by_band),
        )

    @staticmethod
    def _consistent(by_band: dict[str, list[int]]) -> bool:
        """A harder band fully right while an easier band is at most half right suggests lucky guesses."""
        fractions = [right / total for right, total in by_band.values() if total]
        return not any(
            fractions[harder] == 1 and fractions[easier] <= 0.5
            for easier in range(len(fractions))
            for harder in range(easier + 1, len(fractions))
        )


@dataclass(frozen=True)
class RoutingThresholds:
    """`RoutingPolicy` for a given set of settings, in numbers of correct answers out of `questions_total`: a score at
    or below `foundations_max` goes to the prerequisites, one at or above `mastery_min` can be mastery (with the relaxed
    rule the hard band must also be right), anything between is the lesson."""

    questions_total: int
    foundations_max: int
    mastery_min: int


class RoutingPolicy:
    """Where the learner goes after a quiz. The thresholds are the lesson's `FlowSettings` snapshot."""

    def thresholds(self, settings: dict) -> RoutingThresholds:
        total = settings.get("diagnostic_questions_per_band", 2) * len(BANDS)
        strict = settings.get("mastery_requires_all_correct", True)
        return RoutingThresholds(
            questions_total=total,
            foundations_max=settings.get("prereq_trigger_max_correct", 2),
            mastery_min=total if strict else total - 1,
        )

    def route_for(self, result: QuizResult, settings: dict) -> Route:
        hard_right, hard_total = result.by_band.get("hard", [0, 0])
        all_hard = hard_total > 0 and hard_right == hard_total
        if settings.get("mastery_requires_all_correct", True):
            mastered = result.correct == result.total
        else:
            mastered = all_hard and result.correct >= result.total - 1
        if mastered and result.total > 0:
            return "mastery"
        if result.correct <= settings.get("prereq_trigger_max_correct", 2):
            return "prerequisite"
        return "lesson"

    def prerequisites_to_cover(
        self, prerequisites: list[dict], questions: list[dict], result: QuizResult
    ) -> list[dict]:
        """0/5 → all prerequisites, 5/5 → none, partial → only the missed ones (in the original order)."""
        missed = {q["prerequisite"].strip().lower() for q in questions if not result.per_question[q["id"]]}
        return [p for p in prerequisites if p["name"].strip().lower() in missed]


@dataclass(frozen=True)
class QuestionGrade:
    question_id: str
    marks: int
    correct: bool | None  # None: not marked here (open-ended)
    awarded: int | None


@dataclass(frozen=True)
class SheetGrade:
    grades: list[QuestionGrade]

    @property
    def awarded(self) -> int:
        return sum(g.awarded or 0 for g in self.grades)

    @property
    def available(self) -> int:
        """Marks of the questions that were marked here."""
        return sum(g.marks for g in self.grades if g.correct is not None)

    @property
    def open_marks(self) -> int:
        """Marks of the questions left to self-checking or a model."""
        return sum(g.marks for g in self.grades if g.correct is None)

    @property
    def correct(self) -> int:
        return sum(1 for g in self.grades if g.correct)

    @property
    def marked(self) -> int:
        return sum(1 for g in self.grades if g.correct is not None)


class AnswerGrader:
    """Marks the answers that have exactly one right answer; open-ended ones get no verdict.

    One grader for practice sheets and the lesson test, so a learner's score never depends on where they took it.
    """

    NUMBER = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([^\d\s.+-].*)?$")

    def grade(self, question: dict, answer: Any) -> QuestionGrade:
        marks = question["marks"]
        kind = question["type"]
        if kind == "mcq":
            right = self._is_int(answer) and answer == question["correct_index"]
        elif kind == "numerical":
            right = self._numerical(question, answer)
        else:
            return QuestionGrade(question["id"], marks, None, None)
        return QuestionGrade(question["id"], marks, right, marks if right else 0)

    def grade_all(self, questions: list[dict], answers: dict) -> SheetGrade:
        return SheetGrade([self.grade(q, answers.get(q["id"])) for q in questions])

    @staticmethod
    def _is_int(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    def _numerical(self, question: dict, answer: Any) -> bool:
        value = self._number(answer)
        if value is None or not math.isfinite(value):
            return False
        return abs(value - question["answer"]) <= question["tolerance"] + 1e-9

    def _number(self, answer: Any) -> float | None:
        if isinstance(answer, bool):
            return None
        if isinstance(answer, (int, float)):
            return float(answer)
        if isinstance(answer, str) and (match := self.NUMBER.match(answer)):
            return float(match.group(1))
        return None


class Solution:
    """What a question's answer is made of, for showing after the learner has answered (never before)."""

    FIELDS = (
        "correct_index", "answer", "tolerance", "unit", "model_answer", "key_points", "rubric", "reference_solution",
        "test_cases",
    )  # fmt: skip

    @classmethod
    def of(cls, question: dict) -> dict:
        return {key: question[key] for key in cls.FIELDS if question.get(key) is not None}


class ScoreCard:
    """The result of a submitted lesson test, as the learner sees it (`TestSubmission.result`).

    Questions with one right answer are marked by `AnswerGrader`; the others carry the marks a model gave them, or are
    still waiting for them (`awarded` is None and the card is not `complete`). A blank answer is 0 without asking
    anyone. Topics to revisit are the concepts of the questions that lost marks, the biggest loss first.
    """

    NO_ANSWER = "No answer given."

    def build(self, questions: list[dict], answers: dict, sheet: SheetGrade, model: dict[str, dict] | None) -> dict:
        rows = [
            self._row(q, answers.get(q["id"]), grade, model) for q, grade in zip(questions, sheet.grades, strict=True)
        ]
        awarded = sum(row["awarded"] or 0 for row in rows)
        available = sum(row["marks"] for row in rows)
        return {
            "complete": all(row["awarded"] is not None for row in rows),
            "score": {
                "awarded": awarded,
                "available": available,
                "percent": round(100 * awarded / available) if available else 0,
            },  # fmt: skip
            "questions": rows,
            "topics_to_revisit": self._topics(rows),
        }

    def open_items(self, questions: list[dict], answers: dict) -> list[dict]:
        """The open-ended questions that have an answer to grade, with that answer, for `test.grade`."""
        return [
            q | {"answer": answers[q["id"]]}
            for q in questions
            if q["type"] not in ("mcq", "numerical") and not self._blank(answers.get(q["id"]))
        ]

    def _row(self, question: dict, answer, grade: QuestionGrade, model: dict[str, dict] | None) -> dict:
        row = {"id": question["id"], "type": question["type"], "concept": question["concept"], "marks": grade.marks}
        row["solution"] = Solution.of(question)
        if self._blank(answer):
            return row | {"awarded": 0, "correct": False, "graded_by": "auto", "feedback": self.NO_ANSWER}
        if grade.correct is not None:
            return row | {
                "awarded": grade.awarded, "correct": grade.correct, "graded_by": "auto",
                "feedback": "Correct." if grade.correct else self._expected(question),
            }  # fmt: skip
        given = (model or {}).get(question["id"])
        if given is None:
            return row | {"awarded": None, "correct": None, "graded_by": "none", "feedback": ""}
        awarded = min(given["awarded"], grade.marks)
        return row | {
            "awarded": awarded, "correct": awarded == grade.marks, "graded_by": "model", "feedback": given["feedback"],
        }  # fmt: skip

    @staticmethod
    def _blank(answer) -> bool:
        return answer is None or (isinstance(answer, str) and not answer.strip())

    @staticmethod
    def _expected(question: dict) -> str:
        if question["type"] == "mcq":
            return f'The correct answer is "{question["options"][question["correct_index"]]}".'
        unit = f" {question['unit']}" if question.get("unit") else ""
        return f"The expected answer is {question['answer']:g}{unit} (accepted within ±{question['tolerance']:g})."

    @staticmethod
    def _topics(rows: list[dict]) -> list[str]:
        lost = [
            (row["marks"] - row["awarded"], n, row["concept"])
            for n, row in enumerate(rows)
            if row["awarded"] is not None and row["awarded"] < row["marks"]
        ]
        topics: list[str] = []
        for _, _, concept in sorted(lost, key=lambda item: (-item[0], item[1])):
            if concept not in topics:
                topics.append(concept)
        return topics

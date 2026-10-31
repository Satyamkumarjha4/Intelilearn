"""What a finished quiz attempt says about the learner, for the things that grow out of it: a lesson made from a topic
quiz
and the "study this" advice after a quiz made from lessons.
"""

from dataclasses import dataclass, field

from graph.assessment import AssessmentRequest
from graph.scoring import ScoreBand

from .models import QuickQuizAttempt


@dataclass(frozen=True)
class QuizResultFacts:
    """The level the quiz was written at, how the attempt went, and which concepts it showed as known and as gaps."""

    base_level: str
    band: str
    known_concepts: list[str] = field(default_factory=list)
    weak_concepts: list[str] = field(default_factory=list)

    DEFAULT_LEVEL = "foundation"

    @classmethod
    def of(cls, attempt: QuickQuizAttempt) -> "QuizResultFacts":
        card = attempt.result or {}
        score = card.get("score") or {}
        band = attempt.band or (
            ScoreBand.of(score["awarded"], score["available"]).value if score.get("available") else "normal"
        )
        full = [row["concept"] for row in card.get("questions") or [] if row.get("awarded") == row.get("marks")]
        weak = list(card.get("topics_to_revisit") or [])
        return cls(
            attempt.quiz.level or cls.DEFAULT_LEVEL,
            band,
            [concept for concept in dict.fromkeys(full) if concept and concept not in weak],
            weak,
        )

    def request(self) -> AssessmentRequest:
        return AssessmentRequest(
            base_level=self.base_level,
            band=self.band,
            known_concepts=self.known_concepts,
            weak_concepts=self.weak_concepts,
        )

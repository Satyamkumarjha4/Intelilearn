"""The alignment judge: is the authored lesson right for this topic and this learner?"""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field


class AlignmentIssue(BaseModel):
    target: Literal["page", "final_test", "interactive", "media"]
    target_id: str = Field(description="Page key, question id, or interactive/media spec id.")
    severity: Literal["minor", "major"] = Field(description="major: wrong facts, wrong level, missing prerequisite.")
    problem: str
    fix_instruction: str = Field(description="A concrete instruction for whoever rewrites the item.")


class AlignmentReport(BaseModel):
    topic_relevance: int = Field(ge=1, le=5)
    level_fit: int = Field(ge=1, le=5, description="Right depth for this learner.")
    prerequisite_coverage: int = Field(ge=1, le=5)
    factual_accuracy: int = Field(ge=1, le=5)
    interactive_relevance: int = Field(ge=1, le=5)
    issues: list[AlignmentIssue] = Field(default_factory=list)
    passed: bool = Field(description="Your overall verdict (recomputed by the system).")

    SCORE_FIELDS: ClassVar[tuple[str, ...]] = (
        "topic_relevance",
        "level_fit",
        "prerequisite_coverage",
        "factual_accuracy",
        "interactive_relevance",
    )

    def recompute_passed(self, min_score: int) -> bool:
        """The LLM's own `passed` is not trusted: every score ≥ min_score and no major issue."""
        scores_ok = all(getattr(self, name) >= min_score for name in self.SCORE_FIELDS)
        return scores_ok and not any(issue.severity == "major" for issue in self.issues)

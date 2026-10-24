"""Stage A: the diagnostic bundle (diagnostic + prerequisite quiz) and the learner assessment."""

from typing import Literal, get_args

from pydantic import BaseModel, Field

Band = Literal["basic", "easy_moderate", "moderate", "moderate_hard", "hard"]
BANDS: tuple[str, ...] = get_args(Band)  # easiest first


class DiagnosticQuestion(BaseModel):
    id: str = Field(description='Short unique id, e.g. "q1".')
    band: Band = Field(description="Difficulty band.")
    concept: str = Field(description="The single concept this question probes. Unique across the quiz.")
    question: str = Field(description="The question text (Markdown; LaTeX between $…$ allowed).")
    options: list[str] = Field(min_length=4, max_length=4, description="Exactly 4 distinct options.")
    correct_index: int = Field(ge=0, le=3, description="Index (0-3) of the one correct option.")
    explanation: str = Field(description="Why the correct option is right, in 1-3 sentences.")


class Prerequisite(BaseModel):
    name: str = Field(description="A concept the learner must know before this topic.")
    why_needed: str = Field(description="One sentence: where the topic relies on it.")


class PrerequisiteQuestion(BaseModel):
    id: str = Field(description='Short unique id, e.g. "p1".')
    prerequisite: str = Field(description="Must equal the name of exactly one prerequisite.")
    question: str
    options: list[str] = Field(min_length=4, max_length=4, description="Exactly 4 distinct options.")
    correct_index: int = Field(ge=0, le=3)
    explanation: str


class DiagnosticBundle(BaseModel):
    diagnostic: list[DiagnosticQuestion] = Field(description="The diagnostic quiz, easiest band first.")
    prerequisites: list[Prerequisite] = Field(description="The prerequisite concepts, most fundamental first.")
    prerequisite_questions: list[PrerequisiteQuestion] = Field(
        description="One basic question per prerequisite, in the same order."
    )


class QuizReviewIssue(BaseModel):
    question_id: str
    problem: str = Field(description="What is wrong and how to fix it.")


class QuizReview(BaseModel):
    """diagnostic.review (optional judge): independence and band calibration."""

    issues: list[QuizReviewIssue] = Field(description="Empty when the quiz is fine.")


class LearnerAssessment(BaseModel):
    level: Literal["novice", "beginner", "intermediate", "advanced"]
    known_concepts: list[str] = Field(description="Concepts the learner has shown they know.")
    gaps: list[str] = Field(description="Concepts to emphasise in the lesson.")
    prerequisites_to_cover: list[str] = Field(description="Copy exactly from the input; do not add or remove.")
    start_point: str = Field(description="Where the core-concepts page should begin, given what they know.")
    author_notes: str = Field(description="Tone, depth and pacing guidance for the page writers.")
    confidence: Literal["low", "medium", "high"] = Field(description="How reliable the quiz evidence is.")

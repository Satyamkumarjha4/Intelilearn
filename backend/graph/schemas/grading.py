"""What `test.grade` returns: marks and feedback for the answers that have no single right answer."""

from pydantic import BaseModel, Field


class GradedAnswer(BaseModel):
    question_id: str
    awarded: int = Field(ge=0, description="Whole marks given, from 0 up to the question's marks.")
    feedback: str = Field(description="One or two sentences to the learner: what was right and what was missing.")


class GradeReport(BaseModel):
    grades: list[GradedAnswer] = Field(description="Exactly one entry for every question you were given.")

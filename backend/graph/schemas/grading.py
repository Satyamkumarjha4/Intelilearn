"""What `test.grade` returns: marks per criterion and feedback for the answers that have no single right answer."""

from pydantic import BaseModel, Field


class GradedAnswer(BaseModel):
    question_id: str
    awards: list[int] = Field(
        description="One whole number per criterion, in the order given: marks awarded, 0 up to that criterion's marks."
    )
    feedback: str = Field(description="One or two sentences to the learner: what was right and what was missing.")


class GradeReport(BaseModel):
    grades: list[GradedAnswer] = Field(description="Exactly one entry for every question you were given.")

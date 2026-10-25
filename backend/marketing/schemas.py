"""Shapes that live inside a `DemoQuestion`'s JSON columns, validated by the model."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class Outcome(BaseModel):
    """Where a learner stands after answering, and where the lesson would begin."""

    model_config = ConfigDict(extra="forbid")

    level: StrictInt = Field(ge=1, le=5)
    level_label: str = Field(min_length=1, max_length=40)
    lesson_start: str = Field(min_length=1, max_length=200)

    @field_validator("level_label", "lesson_start")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

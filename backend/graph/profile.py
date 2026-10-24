"""LearnerProfile: the parts of `accounts.Profile` that shape the content. No name or email ever reaches a model."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LearnerProfile:
    education_level: str
    grade_or_year: str
    field_of_study: str
    preferred_language: str
    learning_preference: str
    goal: str
    notes: str

    @classmethod
    def of(cls, profile) -> "LearnerProfile":
        return cls(
            education_level=profile.get_education_level_display() if profile.education_level else "",
            grade_or_year=profile.grade_or_year,
            field_of_study=profile.field_of_study,
            preferred_language=profile.preferred_language or "en",
            learning_preference=profile.learning_preference,
            goal=profile.get_goal_display() if profile.goal else "",
            notes=profile.notes,
        )

    def as_dict(self) -> dict:
        return asdict(self)

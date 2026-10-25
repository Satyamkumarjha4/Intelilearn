from .models import Profile


class ProfileOptions:
    """The choice lists of a profile as `GET /api/profile/options` serves them: the choices the profile accepts."""

    LISTS = {
        "education_level": Profile.EducationLevel,
        "learning_preference": Profile.LearningPreference,
        "goal": Profile.Goal,
        "preferred_language": Profile.PreferredLanguage,
    }

    def payload(self) -> dict[str, list[dict[str, str]]]:
        return {
            field: [{"value": value, "label": str(label)} for value, label in choices.choices]
            for field, choices in self.LISTS.items()
        }

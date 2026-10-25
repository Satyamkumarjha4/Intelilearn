from rest_framework import serializers

from accounts.models import Profile

from .domain import Source

CHOICE_MESSAGE = {"invalid_choice": "Please choose one of the options."}


class TopicSuggestionsRequestSerializer(serializers.Serializer):
    """What the onboarding form has so far. Validated against the profile's own choices, but nothing is saved."""

    education_level = serializers.ChoiceField(choices=Profile.EducationLevel.choices, error_messages=CHOICE_MESSAGE)
    grade_or_year = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    field_of_study = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    goal = serializers.ChoiceField(choices=Profile.Goal.choices, error_messages=CHOICE_MESSAGE)
    preferred_language = serializers.ChoiceField(
        choices=Profile.PreferredLanguage.choices,
        default=Profile.PreferredLanguage.ENGLISH,
        error_messages=CHOICE_MESSAGE,
    )
    page = serializers.IntegerField(
        min_value=0, max_value=10_000, default=0, help_text="Four topics a page; pages wrap."
    )


class SuggestedTopicSerializer(serializers.Serializer):
    title = serializers.CharField(help_text="In the learner's language.")
    title_en = serializers.CharField(help_text="The English title.")
    subject = serializers.CharField()
    reason = serializers.CharField(help_text="Why it is suggested, in the learner's language.")


class TopicSuggestionsSerializer(serializers.Serializer):
    source = serializers.ChoiceField(
        choices=[(source.value, source.name.title()) for source in Source],
        help_text="`catalogue` (curated), `ai` (a model, for a field the catalogue does not know) or `fallback` "
        "(English catalogue topics because a model could not answer).",
    )
    topics = SuggestedTopicSerializer(many=True, help_text="Exactly four.")
    has_more = serializers.BooleanField(help_text="Whether another page would show other topics.")

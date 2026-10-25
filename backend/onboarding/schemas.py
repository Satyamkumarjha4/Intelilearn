"""The structured output of the `onboarding.suggest_topics` node (a Pydantic model, like those in `graph/schemas`)."""

from pydantic import BaseModel, Field


class SuggestedTopic(BaseModel):
    title: str = Field(min_length=1, max_length=120, description="The topic, in the learner's language.")
    title_en: str = Field(
        max_length=120, description="The same title in English; identical to `title` when the language is English."
    )
    subject: str = Field(min_length=1, max_length=60, description="The subject area, one or two words.")
    reason: str = Field(min_length=1, max_length=160, description="One short sentence on why it suits this learner.")


class TopicSuggestions(BaseModel):
    # Six to eight are asked for when suggesting; a translated page has four, so four is the floor.
    topics: list[SuggestedTopic] = Field(min_length=4, max_length=8)

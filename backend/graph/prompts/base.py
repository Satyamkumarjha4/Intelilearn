"""The skeleton every prompt shares (Template Method): a system message, a user message, and the feedback block
that tells the model what its previous attempt got wrong.

Keep the rules stated here in sync with `graph/validators`: the validator's messages are sent back as feedback, so
the prompt should already state every rule the validator enforces.

`subject` is the graph state (or a `Send` branch) plus whatever extra the prompt needs, such as the page plan.
"""

import json
from abc import ABC, abstractmethod

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German"}


class Prompt(ABC):
    def messages(self, subject: dict, feedback: list[str] | None = None) -> list[BaseMessage]:
        return [SystemMessage(self.system(subject)), HumanMessage(self.user(subject) + self.feedback_block(feedback))]

    @abstractmethod
    def system(self, subject: dict) -> str: ...

    @abstractmethod
    def user(self, subject: dict) -> str: ...

    @staticmethod
    def to_json(data) -> str:
        return json.dumps(data, ensure_ascii=False, indent=1)

    @staticmethod
    def feedback_block(feedback: list[str] | None) -> str:
        if not feedback:
            return ""
        items = "\n".join(f"- {item}" for item in feedback)
        return f"\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED. Fix every one of these problems:\n{items}"

    @staticmethod
    def language_rule(profile: dict | None) -> str:
        code = (profile or {}).get("preferred_language") or "en"
        return f"Write all learner-facing text in {LANGUAGE_NAMES.get(code, code)}."

    @staticmethod
    def learner_text(profile: dict | None) -> str:
        fields = [
            ("Education level", "education_level"),
            ("Grade / year", "grade_or_year"),
            ("Field of study", "field_of_study"),
            ("Learning preference", "learning_preference"),
            ("Goal", "goal"),
            ("Notes from the learner", "notes"),
        ]
        lines = [f"- {label}: {profile[key]}" for label, key in fields if (profile or {}).get(key)]
        return "\n".join(lines) or "- (no profile details)"

    @staticmethod
    def topic_text(subject: dict) -> str:
        context = subject.get("user_context")
        return f'Topic: "{subject["topic"]}"' + (f"\nWhat the learner says about it: {context}" if context else "")

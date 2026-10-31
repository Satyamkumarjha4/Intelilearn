"""What kind of topic a quiz is about, as far as the choice of questions goes (plan §9.5). Pure."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicTraits:
    """Whether a topic is mainly calculation (numerical questions make sense) and whether it is about programming (the
    answers to short and long questions may be code). Judged by the cheap `topic.traits` model call for a topic, and
    read
    from the plan and pages, with no model, for a lesson."""

    quantitative: bool
    programming: bool

    @classmethod
    def everything(cls) -> "TopicTraits":
        """For a topic nobody could judge: offer all that the count allows."""
        return cls(quantitative=True, programming=True)

    def as_dict(self) -> dict:
        return {"quantitative": self.quantitative, "programming": self.programming}

    @classmethod
    def from_dict(cls, data) -> "TopicTraits | None":
        """The traits that were stored, or None when what is stored is not traits (a cache entry from another"
        " version)."""
        if not isinstance(data, dict):
            return None
        quantitative, programming = data.get("quantitative"), data.get("programming")
        if not isinstance(quantitative, bool) or not isinstance(programming, bool):
            return None
        return cls(quantitative, programming)

    @classmethod
    def of_lessons(cls, lessons: list[tuple[dict | None, dict | None]]) -> "TopicTraits":
        """From the lessons' `(plan, pages)`: quantitative if any plan says so, programming if any page has code."""
        quantitative = any(bool((plan or {}).get("quantitative")) for plan, _ in lessons)
        programming = any(cls._has_code(pages) for _, pages in lessons)
        return cls(quantitative, programming)

    @staticmethod
    def _has_code(pages: dict | None) -> bool:
        return any(
            section.get("code_snippets")
            for page in (pages or {}).values()
            for section in (page or {}).get("sections") or []
        )

"""Which catalogue list a learner's answers lead to (a chain of rules, first match wins)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .catalogue import Catalogue, CatalogueItem
from .domain import SuggestionRequest


@dataclass(frozen=True)
class Route:
    items: tuple[CatalogueItem, ...]
    # False when the learner named a field the catalogue does not know: `items` is then only the fallback, and a model
    # may be asked for better.
    matched: bool
    # Tells lists apart (class, family, field), for the cache.
    key: str


class RouteRule(ABC):
    @abstractmethod
    def route(self, request: SuggestionRequest, catalogue: Catalogue) -> Route | None:
        """The route, or None when this rule is not for this learner."""


class SchoolRule(RouteRule):
    def route(self, request, catalogue):
        if request.education_level != "school":
            return None
        grade = request.school_class
        return Route(catalogue.school(grade), True, f"school:class-{grade}" if grade else "school:general")


class InterviewRule(RouteRule):
    def route(self, request, catalogue):
        return Route(catalogue.interview_prep(), True, "interview") if request.goal == "interview_prep" else None


class HigherEducationRule(RouteRule):
    def route(self, request, catalogue):
        level = request.education_level
        if level not in ("undergraduate", "postgraduate"):
            return None
        if not request.has_field:
            return Route(catalogue.general(level), True, f"{level}:general")
        if family := catalogue.families.match(request.field_of_study):
            return Route(catalogue.family(family, level), True, f"{level}:{family}")
        return Route(catalogue.general(level), False, f"{level}:field-{request.field_slug}")


class ProfessionalRule(RouteRule):
    def route(self, request, catalogue):
        return (
            Route(catalogue.professional(), True, "professional") if request.education_level == "professional" else None
        )


class SelfLearnerRule(RouteRule):
    """The last resort, so every request has a list."""

    def route(self, request, catalogue):
        return Route(catalogue.self_learner(), True, "self_learner")


class TopicRouter:
    def __init__(self, catalogue: Catalogue, rules: list[RouteRule] | None = None):
        self._catalogue = catalogue
        self._rules = rules if rules is not None else [
            SchoolRule(), InterviewRule(), HigherEducationRule(), ProfessionalRule(), SelfLearnerRule(),
        ]  # fmt: skip

    def route(self, request: SuggestionRequest) -> Route:
        for rule in self._rules:
            if route := rule.route(request, self._catalogue):
                return route
        raise LookupError("no routing rule matched; the last rule should match everything")

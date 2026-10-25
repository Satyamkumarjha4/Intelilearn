"""The line under a suggested topic that says why it is there, built from rules over what the learner said."""

from abc import ABC, abstractmethod

from .domain import SuggestionRequest


class ReasonRule(ABC):
    @abstractmethod
    def applies(self, request: SuggestionRequest) -> bool: ...

    @abstractmethod
    def text(self, request: SuggestionRequest) -> str: ...


class ExamPrep(ReasonRule):
    def applies(self, request: SuggestionRequest) -> bool:
        return request.goal == "exam_prep"

    def text(self, request: SuggestionRequest) -> str:
        return f"{request.grade_label} · often in exams" if request.grade_label else "Often in exams"


class InterviewPrep(ReasonRule):
    def applies(self, request: SuggestionRequest) -> bool:
        return request.goal == "interview_prep"

    def text(self, request: SuggestionRequest) -> str:
        return "Common in interviews"


class School(ReasonRule):
    def applies(self, request: SuggestionRequest) -> bool:
        return request.education_level == "school"

    def text(self, request: SuggestionRequest) -> str:
        return f"In your {request.grade_label} syllabus" if request.grade_label else "Popular with students"


class SelfLearner(ReasonRule):
    def applies(self, request: SuggestionRequest) -> bool:
        return request.education_level == "self_learner"

    def text(self, request: SuggestionRequest) -> str:
        return "Popular with self-learners"


class Professional(ReasonRule):
    def applies(self, request: SuggestionRequest) -> bool:
        return request.education_level == "professional"

    def text(self, request: SuggestionRequest) -> str:
        return "Useful at work"


class ReasonBuilder:
    """The first rule that applies wins; the last line is for everyone else (undergraduates and postgraduates)."""

    DEFAULT = "Picked for your course"

    def __init__(self, rules: list[ReasonRule] | None = None):
        self._rules = (
            rules if rules is not None else [ExamPrep(), InterviewPrep(), School(), SelfLearner(), Professional()]
        )

    def reason(self, request: SuggestionRequest) -> str:
        return next((rule.text(request) for rule in self._rules if rule.applies(request)), self.DEFAULT)

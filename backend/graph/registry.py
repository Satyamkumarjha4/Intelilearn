"""GraphRegistry: `GraphRun.graph` name → the builder that assembles that graph."""

from .attempt_stores import LessonAttemptStore, QuizAttemptStore
from .builders import (
    FlowGraphBuilder,
    GradeAttemptGraphBuilder,
    GraphBuilder,
    QuestionBankGraphBuilder,
    QuickQuizGraphBuilder,
    RuntimeRepairGraphBuilder,
    StudyMaterialGraphBuilder,
)


class UnknownGraph(KeyError):
    pass


class GraphRegistry:
    def __init__(self, builders: dict[str, GraphBuilder] | None = None):
        self.builders = (
            builders
            if builders is not None
            else {
                "flow": FlowGraphBuilder(),
                "study_material": StudyMaterialGraphBuilder(),
                "runtime_repair": RuntimeRepairGraphBuilder(),
                "grade_test": GradeAttemptGraphBuilder(LessonAttemptStore()),
                "grade_quiz": GradeAttemptGraphBuilder(QuizAttemptStore()),
                "question_bank": QuestionBankGraphBuilder(),
                "quick_quiz": QuickQuizGraphBuilder(),
            }
        )

    def builder(self, name: str) -> GraphBuilder:
        try:
            return self.builders[name]
        except KeyError:
            raise UnknownGraph(f"Unknown graph {name!r}; known graphs: {', '.join(sorted(self.builders))}") from None

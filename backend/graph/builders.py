"""Graph builders (Builder pattern): nodes and edges are added step by step, then the graph is compiled.

The lesson flow is assembled from segments, one per slice of the graph (diagnose, mastery, author, build, failure).
A segment adds its own nodes and edges and is told where its exits lead, so a segment that is not part of the
graph yet (the author stage, before it lands) simply leaves its exit at END.
"""

from abc import ABC, abstractmethod

from langgraph.graph import END, START, StateGraph

from .context import FlowContext
from .nodes.diagnose import (
    AssessLearnerNode,
    AwaitDiagnosticNode,
    AwaitPrerequisiteNode,
    GenerateDiagnosticNode,
    GradeDiagnosticNode,
    GradePrerequisiteNode,
    LoadContextNode,
    PublishDiagnosticNode,
    PublishPrerequisiteNode,
    ValidateDiagnosticNode,
)
from .nodes.failure import AwaitRetryNode, MarkFailedNode
from .nodes.mastery import (
    AwaitChoiceNode,
    FailStudyMaterialNode,
    GenerateStudyMaterialNode,
    PersistStudyMaterialNode,
    PublishMasteryOptionsNode,
    ValidateStudyMaterialNode,
)
from .nodes.routers import CheckRouter, LevelRouter
from .state import FlowState


class GraphBuilder(ABC):
    state_schema: type = FlowState

    def build(self, checkpointer=None):
        graph = StateGraph(self.state_schema, context_schema=FlowContext)
        self.add_nodes(graph)
        self.add_edges(graph)
        return graph.compile(checkpointer=checkpointer)

    @abstractmethod
    def add_nodes(self, graph: StateGraph) -> None: ...

    @abstractmethod
    def add_edges(self, graph: StateGraph) -> None: ...


class Segment(ABC):
    """One slice of the flow graph."""

    #: Nodes a retry may resume at (the ones that give up with `failed_node` set).
    retry_targets: tuple[str, ...] = ()
    #: Entry points this segment offers to the others: exit name → node. The author segment provides `lesson`.
    provides: dict[str, str] = {}

    @abstractmethod
    def add_nodes(self, graph: StateGraph) -> None: ...

    @abstractmethod
    def add_edges(self, graph: StateGraph, exits: dict[str, str]) -> None:
        """`exits` maps exit names (`lesson`, `mastery`, `failed`) to the node each leads to."""


class DiagnoseSegment(Segment):
    """Stage A: START → … → assess_learner. Exits: `mastery` (aced it), `lesson` (after the assessment), `failed`."""

    retry_targets = ("load_context", "generate_diagnostic")

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (
            LoadContextNode(),
            GenerateDiagnosticNode(),
            ValidateDiagnosticNode(),
            PublishDiagnosticNode(),
            AwaitDiagnosticNode(),
            GradeDiagnosticNode(),
            PublishPrerequisiteNode(),
            AwaitPrerequisiteNode(),
            GradePrerequisiteNode(),
            AssessLearnerNode(),
        ):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph, exits: dict[str, str]) -> None:
        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "generate_diagnostic")
        graph.add_edge("generate_diagnostic", "validate_diagnostic")
        graph.add_conditional_edges(
            "validate_diagnostic",
            CheckRouter("diagnostic", ok="publish_diagnostic", retry="generate_diagnostic", fail=exits["failed"]),
            ["publish_diagnostic", "generate_diagnostic", exits["failed"]],
        )
        graph.add_edge("publish_diagnostic", "await_diagnostic")
        graph.add_edge("await_diagnostic", "grade_diagnostic")
        destinations = {"mastery": exits["mastery"], "prerequisite": "publish_prerequisite", "lesson": "assess_learner"}
        graph.add_conditional_edges("grade_diagnostic", LevelRouter(destinations), sorted(set(destinations.values())))
        graph.add_edge("publish_prerequisite", "await_prerequisite")
        graph.add_edge("await_prerequisite", "grade_prerequisite")
        graph.add_edge("grade_prerequisite", "assess_learner")
        graph.add_edge("assess_learner", exits["lesson"])


class MasterySegment(Segment):
    """The learner aced the diagnostic: offer a sheet, write it, check it, save it. Provides the `mastery` exit."""

    retry_targets = ("generate_study_material",)
    provides = {"mastery": "publish_mastery_options"}

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (
            PublishMasteryOptionsNode(),
            AwaitChoiceNode(),
            GenerateStudyMaterialNode(),
            ValidateStudyMaterialNode(),
            PersistStudyMaterialNode(),
        ):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph, exits: dict[str, str]) -> None:
        graph.add_edge("publish_mastery_options", "await_choice")
        graph.add_edge("await_choice", "generate_study_material")
        graph.add_edge("generate_study_material", "validate_study_material")
        graph.add_conditional_edges(
            "validate_study_material",
            CheckRouter("material", ok="persist_study_material", retry="generate_study_material", fail=exits["failed"]),
            ["persist_study_material", "generate_study_material", exits["failed"]],
        )
        graph.add_edge("persist_study_material", END)


class FailureSegment(Segment):
    """`mark_failed` records why; `await_retry` pauses until the learner presses Retry."""

    def __init__(self, retry_targets: tuple[str, ...]):
        self.retry_targets = retry_targets

    def add_nodes(self, graph: StateGraph) -> None:
        graph.add_node(MarkFailedNode.name, MarkFailedNode())
        graph.add_node(AwaitRetryNode.name, AwaitRetryNode(), destinations=self.retry_targets)

    def add_edges(self, graph: StateGraph, exits: dict[str, str]) -> None:
        graph.add_edge("mark_failed", "await_retry")


class FlowGraphBuilder(GraphBuilder):
    """The lesson flow: one thread per lesson (`thread_id` = lesson id). See docs/lesson-graph.md."""

    def __init__(self, segments: list[Segment] | None = None):
        self.segments = segments if segments is not None else self.default_segments()

    @staticmethod
    def default_segments() -> list[Segment]:
        return [DiagnoseSegment(), MasterySegment()]

    def _exits(self) -> dict[str, str]:
        # Exits that no segment provides lead to END.
        exits = {"failed": "mark_failed", "lesson": END, "mastery": END}
        for segment in self.segments:
            exits |= segment.provides
        return exits

    def add_nodes(self, graph: StateGraph) -> None:
        for segment in self.segments:
            segment.add_nodes(graph)
        FailureSegment(self._retry_targets()).add_nodes(graph)

    def add_edges(self, graph: StateGraph) -> None:
        exits = self._exits()
        for segment in self.segments:
            segment.add_edges(graph, exits)
        FailureSegment(self._retry_targets()).add_edges(graph, exits)

    def _retry_targets(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(t for segment in self.segments for t in segment.retry_targets))


class StudyMaterialGraphBuilder(GraphBuilder):
    """Another sheet for a lesson that is already ready: generate → validate → persist, in its own thread.

    Input: `{"lesson_id", "mastery_choice": kind, "extra_material": True}`. There is no Retry: a failed run ends with
    its reason and the learner asks again.
    """

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (
            LoadContextNode(),
            GenerateStudyMaterialNode(),
            ValidateStudyMaterialNode(),
            PersistStudyMaterialNode(),
            FailStudyMaterialNode(),
        ):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph) -> None:
        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "generate_study_material")
        graph.add_edge("generate_study_material", "validate_study_material")
        graph.add_conditional_edges(
            "validate_study_material",
            CheckRouter(
                "material", ok="persist_study_material", retry="generate_study_material", fail="fail_study_material"
            ),
            ["persist_study_material", "generate_study_material", "fail_study_material"],
        )
        graph.add_edge("persist_study_material", END)

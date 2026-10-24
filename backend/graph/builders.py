"""Graph builders (Builder pattern): nodes and edges are added step by step, then the graph is compiled.

The lesson flow is assembled from segments, one per slice of the graph (diagnose, mastery, author, build, failure).
A segment adds its own nodes and edges and is told where its exits lead, so a segment that is not part of the
graph yet (the author stage, before it lands) simply leaves its exit at END.
"""

from langgraph.graph import END, START, StateGraph

from .builder_base import GraphBuilder, Segment
from .nodes.author import (
    AlignmentJudgeNode,
    AuthoredJoinNode,
    BuildInteractiveNode,
    FindMediaNode,
    FixItemNode,
    PlanInteractivesNode,
    PlanLessonNode,
    ValidateInteractivePlanNode,
    ValidatePlanNode,
    WidgetsJoinNode,
    WritePageNode,
    WriteTestNode,
)
from .nodes.author_routers import (
    AlignmentRouter,
    AuthoringRouter,
    InteractivePlanRouter,
    PlanRouter,
    WidgetRouter,
)
from .nodes.build import (
    AssembleDocumentNode,
    CompilePageNode,
    PersistLessonNode,
    PrepareBuildNode,
    RenderCheckNode,
    RepairComponentNode,
    RepairPageNode,
)
from .nodes.build_routers import AssembledRouter, BuildRouter, RenderRouter
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
from .nodes.repair import (
    AssembleRepairedNode,
    LoadRepairNode,
    RegressionCheckNode,
    RepairRuntimeNode,
    SaveRepairNode,
    VerifyRepairNode,
)
from .nodes.routers import CheckRouter, LevelRouter


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


class AuthorSegment(Segment):
    """Stage B: plan, write the pages and the test in parallel, plan and build the interactives and media in parallel,
    then the alignment judge. Provides the `lesson` exit; its own exit, `build`, leads on to Stage C."""

    retry_targets = ("plan_lesson", "alignment_judge")
    provides = {"lesson": "plan_lesson"}

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (
            PlanLessonNode(),
            ValidatePlanNode(),
            WritePageNode(),
            WriteTestNode(),
            AuthoredJoinNode(),
            PlanInteractivesNode(),
            ValidateInteractivePlanNode(),
            FindMediaNode(),
            BuildInteractiveNode(),
            WidgetsJoinNode(),
            AlignmentJudgeNode(),
            FixItemNode(),
        ):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph, exits: dict[str, str]) -> None:
        failed = exits["failed"]
        graph.add_edge("plan_lesson", "validate_plan")
        graph.add_conditional_edges("validate_plan", PlanRouter(), ["write_page", "write_test", "plan_lesson", failed])
        graph.add_edge("write_page", "authored_join")
        graph.add_edge("write_test", "authored_join")
        graph.add_conditional_edges(
            "authored_join", AuthoringRouter(), ["write_page", "write_test", "plan_interactives"]
        )
        graph.add_edge("plan_interactives", "validate_interactive_plan")
        graph.add_conditional_edges(
            "validate_interactive_plan",
            InteractivePlanRouter(),
            ["find_media", "build_interactive", "widgets_join", "plan_interactives"],
        )
        graph.add_edge("find_media", "widgets_join")
        graph.add_edge("build_interactive", "widgets_join")
        graph.add_conditional_edges(
            "widgets_join", WidgetRouter(), ["find_media", "build_interactive", "alignment_judge"]
        )
        graph.add_conditional_edges(
            "alignment_judge",
            AlignmentRouter(on_pass=exits["build"], on_fail=failed),
            ["fix_item", exits["build"], failed],
        )
        graph.add_edge("fix_item", "alignment_judge")


class BuildSegment(Segment):
    """Stage C: compile the pages in parallel, assemble, render check in headless Chromium, repair only what broke,
    persist. Provides the `build` exit (the author segment's exit after the alignment judge)."""

    retry_targets = ("assemble_document",)
    provides = {"build": "prepare_build"}

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (
            PrepareBuildNode(),
            CompilePageNode(),
            AssembleDocumentNode(),
            RenderCheckNode(),
            RepairPageNode(),
            RepairComponentNode(),
            PersistLessonNode(),
        ):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph, exits: dict[str, str]) -> None:
        failed = exits["failed"]
        graph.add_conditional_edges("prepare_build", BuildRouter(), ["compile_page"])
        graph.add_edge("compile_page", "assemble_document")
        graph.add_conditional_edges("assemble_document", AssembledRouter(), ["render_check", failed])
        graph.add_conditional_edges(
            "render_check",
            RenderRouter(),
            ["persist_lesson", "repair_page", "repair_component", "assemble_document", failed],
        )
        graph.add_edge("repair_page", "assemble_document")
        graph.add_edge("repair_component", "assemble_document")
        graph.add_edge("persist_lesson", END)


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
        return [DiagnoseSegment(), MasterySegment(), AuthorSegment(), BuildSegment()]

    def _exits(self) -> dict[str, str]:
        # Exits that no segment provides lead to END.
        exits = {"failed": "mark_failed", "lesson": END, "mastery": END, "build": END}
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


class RuntimeRepairGraphBuilder(GraphBuilder):
    """A ready lesson that crashed in the browser: repair the one page or interactive, check it, save a new version.

    Input: `{"lesson_id", "repair_error", "expected_code_version"}`. Every step either goes on or raises `RepairFailed`,
    so the graph is a line: there is no Retry, and a failed run leaves the lesson as it was.
    """

    STEPS = (
        LoadRepairNode,
        RepairRuntimeNode,
        AssembleRepairedNode,
        RegressionCheckNode,
        VerifyRepairNode,
        SaveRepairNode,
    )

    def add_nodes(self, graph: StateGraph) -> None:
        for step in self.STEPS:
            node = step()
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph) -> None:
        names = [step.name for step in self.STEPS]
        graph.add_edge(START, names[0])
        for before, after in zip(names, names[1:], strict=False):
            graph.add_edge(before, after)
        graph.add_edge(names[-1], END)

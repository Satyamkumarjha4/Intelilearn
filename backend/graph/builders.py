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
)
from .nodes.author_routers import (
    AlignmentRouter,
    AuthoringRouter,
    BatchesRouter,
    InteractivePlanRouter,
    PlanRouter,
    WidgetRouter,
)
from .nodes.bank import (
    BankBatchesRouter,
    BankJoinNode,
    BankRouter,
    FailAttemptNode,
    LoadBankNode,
    PersistAttemptNode,
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
from .nodes.entry import (
    AssessFromSourceNode,
    EntryRouter,
    EntryRouterNode,
    IntentRouter,
    IntentRouterNode,
    LevelGate,
    LevelGateNode,
    PlanPrerequisitesNode,
    ValidatePrerequisitesNode,
)
from .nodes.failure import AwaitRetryNode, MarkFailedNode
from .nodes.grading import (
    FailGradeNode,
    GradeOpenNode,
    LoadSubmissionNode,
    OpenItemsRouter,
    PersistGradeNode,
    ValidateGradeNode,
)
from .nodes.mastery import (
    AwaitChoiceNode,
    FailStudyMaterialNode,
    GenerateStudyMaterialNode,
    PersistStudyMaterialNode,
    PublishMasteryOptionsNode,
    ValidateStudyMaterialNode,
)
from .nodes.questions import GenerateQuestionsNode, PlanBatchesNode
from .nodes.repair import (
    AssembleRepairedNode,
    LoadRepairNode,
    RegressionCheckNode,
    RepairRuntimeNode,
    SaveRepairNode,
    VerifyRepairNode,
)
from .nodes.routers import CheckRouter, LevelRouter
from .nodes.sheets import (
    ChoiceRouter,
    GenerateSheetNode,
    PlanSheetsNode,
    PlanSheetsRouter,
    SheetsJoinNode,
    SheetsRouter,
)


class DiagnoseSegment(Segment):
    """Stage A: START → … → assess_learner. Exits: `begin` (where load_context goes: the quick check, unless a segment
    offers another way in), `mastery` (aced it), `assessed` (after the assessment), `failed`. Provides `assess`, the
    assessment, for a learner who chose the Expert lesson."""

    retry_targets = ("load_context", "generate_diagnostic")
    provides = {"assess": "assess_learner"}

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
        graph.add_edge("load_context", exits["begin"])
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
        graph.add_edge("assess_learner", exits["assessed"])


class EntrySegment(Segment):
    """The way in for a learner who took no quick check, and where both ways meet: entry_router, assess_from_source,
    level_gate, plan_prerequisites, intent_router. Provides `begin` (load_context goes to the entry router) and
    `assessed` (every assessment goes to the level gate); the intent router sends a lesson on to the `lesson` exit."""

    retry_targets = ("plan_prerequisites",)
    provides = {"begin": "entry_router", "assessed": "level_gate"}

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (
            EntryRouterNode(),
            AssessFromSourceNode(),
            LevelGateNode(),
            PlanPrerequisitesNode(),
            ValidatePrerequisitesNode(),
            IntentRouterNode(),
        ):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph, exits: dict[str, str]) -> None:
        graph.add_conditional_edges("entry_router", EntryRouter(), ["generate_diagnostic", "assess_from_source"])
        graph.add_edge("assess_from_source", "level_gate")
        graph.add_conditional_edges("level_gate", LevelGate(), ["plan_prerequisites", "intent_router"])
        graph.add_edge("plan_prerequisites", "validate_prerequisites")
        graph.add_conditional_edges(
            "validate_prerequisites",
            CheckRouter("prerequisites", ok="intent_router", retry="plan_prerequisites", fail=exits["failed"]),
            ["intent_router", "plan_prerequisites", exits["failed"]],
        )
        graph.add_conditional_edges("intent_router", IntentRouter({"lesson": exits["lesson"]}), [exits["lesson"]])


class MasterySegment(Segment):
    """The learner aced the diagnostic: offer the Expert lesson or the two sheets (or, for a lesson that was waiting
    before that, one sheet), then follow the choice. Provides the `mastery` exit."""

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
        graph.add_conditional_edges(
            "await_choice",
            ChoiceRouter(lesson=exits["assess"], sheets=exits["sheets"], legacy="generate_study_material"),
            sorted({exits["assess"], exits["sheets"], "generate_study_material"}),
        )
        graph.add_edge("generate_study_material", "validate_study_material")
        graph.add_conditional_edges(
            "validate_study_material",
            CheckRouter("material", ok="persist_study_material", retry="generate_study_material", fail=exits["failed"]),
            ["persist_study_material", "generate_study_material", exits["failed"]],
        )
        graph.add_edge("persist_study_material", END)


class SheetsSegment(Segment):
    """The cheat sheet and the revision sheet, written in parallel and saved together. Provides the `sheets` exit."""

    retry_targets = ("plan_sheets",)
    provides = {"sheets": "plan_sheets"}

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (PlanSheetsNode(), GenerateSheetNode(), SheetsJoinNode()):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph, exits: dict[str, str]) -> None:
        graph.add_conditional_edges("plan_sheets", PlanSheetsRouter(), ["generate_sheet"])
        graph.add_edge("generate_sheet", "sheets_join")
        graph.add_conditional_edges(
            "sheets_join", SheetsRouter(on_fail=exits["failed"]), ["generate_sheet", END, exits["failed"]]
        )


class AuthorSegment(Segment):
    """Stage B: plan, write the pages and the test's batches in parallel, plan and build the interactives and media in
    parallel, then the alignment judge. Provides the `lesson` exit; its own exit, `build`, leads on to Stage C."""

    retry_targets = ("plan_lesson", "plan_batches", "alignment_judge")
    provides = {"lesson": "plan_lesson"}

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (
            PlanLessonNode(),
            ValidatePlanNode(),
            PlanBatchesNode(),
            WritePageNode(),
            GenerateQuestionsNode(),
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
        graph.add_conditional_edges("validate_plan", PlanRouter(), ["plan_batches", "plan_lesson", failed])
        graph.add_conditional_edges(
            "plan_batches", BatchesRouter(), ["write_page", "generate_questions", "authored_join"]
        )
        graph.add_edge("write_page", "authored_join")
        graph.add_edge("generate_questions", "authored_join")
        graph.add_conditional_edges(
            "authored_join",
            AuthoringRouter(on_fail=failed),
            ["write_page", "generate_questions", "plan_batches", "plan_interactives", failed],
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
    """The lesson flow: one thread per lesson (`thread_id` = lesson id). See docs/architecture/lesson-graph.md."""

    def __init__(self, segments: list[Segment] | None = None):
        self.segments = segments if segments is not None else self.default_segments()

    @staticmethod
    def default_segments() -> list[Segment]:
        return [DiagnoseSegment(), EntrySegment(), MasterySegment(), SheetsSegment(), AuthorSegment(), BuildSegment()]

    def _exits(self) -> dict[str, str]:
        # Exits that no segment provides lead to END.
        exits = {"failed": "mark_failed", "lesson": END, "mastery": END, "build": END, "sheets": END}
        for segment in self.segments:
            exits |= segment.provides
        # Without an entry segment the quick check is the only way in, and an assessment leads straight to the lesson.
        exits.setdefault("begin", "generate_diagnostic")
        exits.setdefault("assessed", exits["lesson"])
        exits.setdefault("assess", END)
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


class GradeTestGraphBuilder(GraphBuilder):
    """A submitted lesson test: the open-ended answers are graded by `test.grade`, the rest were marked at once.

    Input: `{"lesson_id", "submission_id"}`, in its own thread. There is no Retry: a failed run ends with its reason
    and the learner submits again.
    """

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (LoadSubmissionNode(), GradeOpenNode(), ValidateGradeNode(), PersistGradeNode(), FailGradeNode()):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph) -> None:
        graph.add_edge(START, "load_submission")
        graph.add_conditional_edges("load_submission", OpenItemsRouter(), ["grade_open", "persist_grade"])
        graph.add_edge("grade_open", "validate_grade")
        graph.add_conditional_edges(
            "validate_grade",
            CheckRouter("grading", ok="persist_grade", retry="grade_open", fail="fail_grade"),
            ["persist_grade", "grade_open", "fail_grade"],
        )
        graph.add_edge("persist_grade", END)


class QuestionBankGraphBuilder(GraphBuilder):
    """A retake's questions: all ten cells of the lesson's blueprint, new, in two batches written in parallel.

    Input: `{"lesson_id", "attempt_id"}`, in its own thread. There is no Retry: a run that cannot fill the test ends
    with its reason and the waiting attempt is removed (`AttemptGenerationEffect`), so the learner starts again.
    """

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (
            LoadBankNode(),
            PlanBatchesNode(),
            GenerateQuestionsNode(),
            BankJoinNode(),
            PersistAttemptNode(),
            FailAttemptNode(),
        ):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph) -> None:
        graph.add_edge(START, "load_bank")
        graph.add_edge("load_bank", "plan_batches")
        graph.add_conditional_edges("plan_batches", BankBatchesRouter(), ["generate_questions", "persist_attempt"])
        graph.add_edge("generate_questions", "questions_join")
        graph.add_conditional_edges(
            "questions_join",
            BankRouter(),
            ["generate_questions", "plan_batches", "persist_attempt", "fail_attempt"],
        )
        graph.add_edge("persist_attempt", END)

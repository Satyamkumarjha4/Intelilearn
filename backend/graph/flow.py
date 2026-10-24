"""The graphs. One `flow` StateGraph thread per lesson (thread_id = lesson id), plus two small graphs for later:
`study_material` (another sheet) and `runtime_repair` (graph/nodes/repair.py). See docs/lesson-graph.md.
"""

from langgraph.graph import END, START, StateGraph

from .context import FlowContext
from .nodes import author, build, diagnose, mastery
from .nodes.common import await_retry, mark_failed
from .nodes.repair import build_runtime_repair_graph
from .state import FlowState

NODES = {
    # Stage A: diagnose
    "load_context": diagnose.load_context,
    "generate_diagnostic": diagnose.generate_diagnostic,
    "validate_diagnostic": diagnose.validate_diagnostic,
    "publish_diagnostic": diagnose.publish_diagnostic,
    "await_diagnostic": diagnose.await_diagnostic,
    "grade_diagnostic": diagnose.grade_diagnostic,
    "publish_prerequisite": diagnose.publish_prerequisite,
    "await_prerequisite": diagnose.await_prerequisite,
    "grade_prerequisite": diagnose.grade_prerequisite,
    "assess_learner": diagnose.assess_learner,
    # mastery path
    "publish_mastery_options": mastery.publish_mastery_options,
    "await_choice": mastery.await_choice,
    "generate_study_material": mastery.generate_study_material,
    "validate_study_material": mastery.validate_study_material,
    "persist_study_material": mastery.persist_study_material,
    # Stage B: author
    "plan_lesson": author.plan_lesson,
    "validate_plan": author.validate_plan,
    "write_page": author.write_page,
    "write_test": author.write_test,
    "authored_join": author.authored_join,
    "plan_interactives": author.plan_interactives,
    "validate_interactive_plan": author.validate_interactive_plan,
    "find_media": author.find_media,
    "build_interactive": author.build_interactive,
    "widgets_join": author.widgets_join,
    "alignment_judge": author.alignment_judge,
    "fix_item": author.fix_item,
    # Stage C: build and verify
    "compile_page": build.compile_page,
    "assemble_document": build.assemble_document,
    "render_check": build.render_check,
    "repair_page": build.repair_page,
    "repair_component": build.repair_component,
    "persist_lesson": build.persist_lesson,
    # failure: mark, then pause until the learner presses Retry
    "mark_failed": mark_failed,
    "await_retry": await_retry,
}

# Where await_retry may resume (the node that gave up).
RETRY_TARGETS = ["generate_diagnostic", "generate_study_material", "plan_lesson", "alignment_judge",
                 "assemble_document", "load_context"]  # fmt: skip


def build_flow(checkpointer=None):
    graph = StateGraph(FlowState, context_schema=FlowContext)
    for name, fn in NODES.items():
        graph.add_node(name, fn, destinations=tuple(RETRY_TARGETS) if name == "await_retry" else None)

    # Stage A
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "generate_diagnostic")
    graph.add_edge("generate_diagnostic", "validate_diagnostic")
    graph.add_conditional_edges("validate_diagnostic", diagnose.after_validate_diagnostic,
                                ["publish_diagnostic", "generate_diagnostic", "mark_failed"])  # fmt: skip
    graph.add_edge("publish_diagnostic", "await_diagnostic")
    graph.add_edge("await_diagnostic", "grade_diagnostic")
    graph.add_conditional_edges("grade_diagnostic", diagnose.route_level,
                                ["publish_mastery_options", "publish_prerequisite", "assess_learner"])  # fmt: skip
    graph.add_edge("publish_prerequisite", "await_prerequisite")
    graph.add_edge("await_prerequisite", "grade_prerequisite")
    graph.add_edge("grade_prerequisite", "assess_learner")
    graph.add_edge("assess_learner", "plan_lesson")

    # mastery
    graph.add_edge("publish_mastery_options", "await_choice")
    graph.add_edge("await_choice", "generate_study_material")
    graph.add_edge("generate_study_material", "validate_study_material")
    graph.add_conditional_edges("validate_study_material", mastery.after_validate_study_material,
                                ["persist_study_material", "generate_study_material", "mark_failed"])  # fmt: skip
    graph.add_edge("persist_study_material", END)

    # Stage B
    graph.add_edge("plan_lesson", "validate_plan")
    graph.add_conditional_edges("validate_plan", author.after_validate_plan,
                                ["write_page", "write_test", "plan_lesson", "mark_failed"])  # fmt: skip
    graph.add_edge("write_page", "authored_join")
    graph.add_edge("write_test", "authored_join")
    graph.add_conditional_edges("authored_join", author.route_authored,
                                ["write_page", "write_test", "plan_interactives"])  # fmt: skip
    graph.add_edge("plan_interactives", "validate_interactive_plan")
    graph.add_conditional_edges("validate_interactive_plan", author.after_validate_interactive_plan,
                                ["find_media", "build_interactive", "widgets_join", "plan_interactives"])  # fmt: skip
    graph.add_edge("find_media", "widgets_join")
    graph.add_edge("build_interactive", "widgets_join")
    graph.add_conditional_edges("widgets_join", author.route_widgets,
                                ["find_media", "build_interactive", "alignment_judge"])  # fmt: skip
    graph.add_conditional_edges("alignment_judge", author.route_alignment,
                                ["fix_item", "compile_page", "mark_failed"])  # fmt: skip
    graph.add_edge("fix_item", "alignment_judge")

    # Stage C
    graph.add_edge("compile_page", "assemble_document")
    graph.add_conditional_edges("assemble_document", build.route_assembled, ["render_check", "mark_failed"])
    graph.add_conditional_edges("render_check", build.route_render,
                                ["persist_lesson", "repair_page", "repair_component", "assemble_document",
                                 "mark_failed"])  # fmt: skip
    graph.add_edge("repair_page", "assemble_document")
    graph.add_edge("repair_component", "assemble_document")
    graph.add_edge("persist_lesson", END)

    graph.add_edge("mark_failed", "await_retry")
    return graph.compile(checkpointer=checkpointer)


def _material_failed(state):
    raise RuntimeError(state.get("error") or "The study sheet could not be written.")


def build_study_material_graph(checkpointer=None):
    """Another sheet type for a mastery lesson: generate → validate → persist (the lesson stays `ready`)."""
    graph = StateGraph(FlowState, context_schema=FlowContext)
    graph.add_node("load_context", diagnose.load_context)
    graph.add_node("generate_study_material", mastery.generate_study_material)
    graph.add_node("validate_study_material", mastery.validate_study_material)
    graph.add_node("persist_study_material", mastery.persist_study_material)
    graph.add_node("mark_failed", _material_failed)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "generate_study_material")
    graph.add_edge("generate_study_material", "validate_study_material")
    graph.add_conditional_edges("validate_study_material", mastery.after_validate_study_material,
                                ["persist_study_material", "generate_study_material", "mark_failed"])  # fmt: skip
    graph.add_edge("persist_study_material", END)
    return graph.compile(checkpointer=checkpointer)


GRAPH_BUILDERS = {
    "flow": build_flow,
    "study_material": build_study_material_graph,
    "runtime_repair": build_runtime_repair_graph,
}

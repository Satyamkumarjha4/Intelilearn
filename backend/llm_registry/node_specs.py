"""What each LLM-backed graph node needs. Defined in code: they change only when the graph changes.

The admin edits *how* a node runs (NodeConfig / NodeModelBinding); these specs decide *what is allowed*:
a binding whose model lacks a required capability, or has too small an output/context window, is refused.
"""

from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"
    VISION = "vision"
    REASONING = "reasoning"


class Effort(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OutputMode(StrEnum):
    STRUCTURED = "structured"  # Pydantic schema via with_structured_output
    TOOLS = "tools"  # tool-calling loop (graph runs the tools)
    TEXT = "text"  # plain text, e.g. generated TSX


class Stage(StrEnum):
    DIAGNOSE = "diagnose"
    AUTHOR = "author"
    BUILD = "build"
    POST = "post"


@dataclass(frozen=True)
class NodeSpec:
    key: str
    stage: Stage
    output: OutputMode
    description: str
    schema_name: str = ""  # Pydantic output model the node expects (documentation only)
    requires: frozenset[Capability] = frozenset()
    min_output_tokens: int = 4096
    min_context: int = 32_000
    default_reasoning: Effort = Effort.MEDIUM
    default_max_attempts: int = 2
    default_max_tool_steps: int | None = None
    optional: bool = False


_S = Capability.STRUCTURED_OUTPUT

_SPECS = [
    NodeSpec("diagnostic.generate", Stage.DIAGNOSE, OutputMode.STRUCTURED,
             "10-question diagnostic across five difficulty bands plus a 5-question prerequisite quiz.",
             "DiagnosticBundle", frozenset({_S}), min_output_tokens=8192),
    NodeSpec("diagnostic.review", Stage.DIAGNOSE, OutputMode.STRUCTURED,
             "Judge: are diagnostic questions independent and correctly banded?",
             "QuizReview", frozenset({_S}), min_output_tokens=2048, default_reasoning=Effort.LOW, optional=True),
    NodeSpec("learner.assess", Stage.DIAGNOSE, OutputMode.STRUCTURED,
             "Turn quiz results and profile into a learner assessment (level, gaps, start point).",
             "LearnerAssessment", frozenset({_S}), min_output_tokens=2048),
    NodeSpec("study.generate", Stage.DIAGNOSE, OutputMode.STRUCTURED,
             "Cheat sheet, revision sheet or practice sheet for learners who already know the topic.",
             "CheatSheet | RevisionSheet | PracticeSheet", frozenset({_S}), min_output_tokens=16384),
    NodeSpec("lesson.plan", Stage.AUTHOR, OutputMode.STRUCTURED,
             "Plan the four lesson pages and the final test spec.",
             "LessonPlan", frozenset({_S}), min_output_tokens=8192, default_reasoning=Effort.HIGH),
    NodeSpec("page.generate", Stage.AUTHOR, OutputMode.STRUCTURED,
             "Write one content page (introduction, core or advanced).",
             "PageContent", frozenset({_S}), min_output_tokens=16384),
    NodeSpec("test.generate", Stage.AUTHOR, OutputMode.STRUCTURED,
             "Write the 10-15 question final test (MCQ, numerical, short, long, code).",
             "FinalTest", frozenset({_S}), min_output_tokens=16384),
    NodeSpec("interactive.plan", Stage.AUTHOR, OutputMode.STRUCTURED,
             "Decide which interactives and media each page gets.",
             "InteractivePlan", frozenset({_S})),
    NodeSpec("media.search", Stage.AUTHOR, OutputMode.TOOLS,
             "Tool-calling agent that searches openly licensed images and GIFs.",
             "MediaSelection", frozenset({Capability.TOOL_CALLING}), min_output_tokens=2048,
             default_reasoning=Effort.LOW, default_max_tool_steps=6),
    NodeSpec("media.verify", Stage.AUTHOR, OutputMode.STRUCTURED,
             "Vision check: does the image show what the spec describes?",
             "MediaVerdict", frozenset({Capability.VISION, _S}), min_output_tokens=1024,
             default_reasoning=Effort.NONE, optional=True),
    NodeSpec("interactive.generate", Stage.AUTHOR, OutputMode.STRUCTURED,
             "Write one self-contained interactive React component.",
             "InteractiveComponent", frozenset({_S}), min_output_tokens=16384),
    NodeSpec("alignment.judge", Stage.AUTHOR, OutputMode.STRUCTURED,
             "Check content and interactives against the topic and the learner's level.",
             "AlignmentReport", frozenset({_S}), min_context=64_000, default_reasoning=Effort.HIGH),
    NodeSpec("page.compile", Stage.BUILD, OutputMode.TEXT,
             "Compile one page to TSX that renders the injected lesson data.",
             min_output_tokens=32768),
    NodeSpec("code.repair", Stage.BUILD, OutputMode.TEXT,
             "Fix TSX that failed static, security or render checks.",
             min_output_tokens=32768),
    NodeSpec("runtime.repair", Stage.POST, OutputMode.TEXT,
             "Fix TSX that threw in the learner's browser.",
             min_output_tokens=32768),
    NodeSpec("test.grade", Stage.POST, OutputMode.STRUCTURED,
             "Grade short, long and code answers against the model answer or rubric.",
             "GradeReport", frozenset({_S})),
]  # fmt: skip

NODE_SPECS: dict[str, NodeSpec] = {spec.key: spec for spec in _SPECS}


def get_spec(node_key: str) -> NodeSpec:
    try:
        return NODE_SPECS[node_key]
    except KeyError:
        raise KeyError(f"Unknown node key {node_key!r}; add a NodeSpec in llm_registry/node_specs.py") from None

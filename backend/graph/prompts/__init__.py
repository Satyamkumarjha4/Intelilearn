"""Prompt builders, one `Prompt` subclass per LLM node (see base.py)."""

from .author import (
    AlignmentPrompt,
    GenerateInteractivePrompt,
    PlanInteractivesPrompt,
    PlanLessonPrompt,
    WritePagePrompt,
    WriteTestPrompt,
)
from .base import Prompt
from .build import CompilePagePrompt, RepairCodePrompt, RuntimeRepairPrompt
from .diagnose import AssessLearnerPrompt, DiagnosticPrompt, DiagnosticReviewPrompt
from .media import MediaAgentPrompt, VerifyMediaPrompt
from .scope import SCOPE_REFERENCE
from .study import StudyMaterialPrompt

__all__ = [
    "SCOPE_REFERENCE", "AlignmentPrompt", "AssessLearnerPrompt", "CompilePagePrompt", "DiagnosticPrompt",
    "DiagnosticReviewPrompt", "GenerateInteractivePrompt", "MediaAgentPrompt", "PlanInteractivesPrompt",
    "PlanLessonPrompt", "Prompt", "RepairCodePrompt", "RuntimeRepairPrompt", "StudyMaterialPrompt",
    "VerifyMediaPrompt", "WritePagePrompt", "WriteTestPrompt",
]  # fmt: skip

"""Graph state. A TypedDict of plain JSON: Pydantic outputs are stored as `model_dump(mode="json")`.

Keys written by parallel `Send` branches need a reducer, otherwise LangGraph raises InvalidUpdateError.
"""

import operator
from typing import Annotated, Any, Literal, TypedDict


class Reducers:
    """LangGraph reducers for the keys that parallel `Send` branches write."""

    @staticmethod
    def merge_dicts(current: dict | None, update: dict | None) -> dict:
        """Shallow merge; a value of None deletes the key (used to drop degraded items)."""
        merged = dict(current or {})
        for key, value in (update or {}).items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def merge_counts(current: dict | None, update: dict | None) -> dict:
        """Add counts per key; a value of None resets the key (used when a failed run is retried)."""
        merged = dict(current or {})
        for key, value in (update or {}).items():
            merged[key] = 0 if value is None else merged.get(key, 0) + value
        return merged


class FlowState(TypedDict, total=False):
    # inputs (load_context)
    lesson_id: str
    topic: str
    user_context: str
    profile: dict  # LearnerProfile
    snapshot: dict  # resolved model registry (Lesson.config_snapshot)
    settings: dict  # FlowSettings snapshot

    # Stage A
    bundle: dict  # DiagnosticBundle
    diagnostic_quiz_id: str
    diagnostic_attempt_id: str
    diagnostic_result: dict  # QuizResult
    prerequisite_quiz_id: str | None
    prerequisite_attempt_id: str | None
    prerequisite_result: dict | None
    prerequisites_to_cover: list[dict]  # Prerequisite
    route: Literal["prerequisite", "lesson", "mastery"]
    assessment: dict  # LearnerAssessment
    mastery_choice: Literal["cheat_sheet", "revision_sheet", "practice_sheet"] | None
    study_material: dict | None

    # Stage B (parallel writers → reducers)
    plan: dict  # LessonPlan
    pages: Annotated[dict[str, dict], Reducers.merge_dicts]  # introduction / core / advanced → PageContent
    final_test: dict | None  # FinalTest
    interactive_plan: dict  # InteractivePlan
    media: Annotated[dict[str, dict], Reducers.merge_dicts]  # spec_id → MediaRef
    interactives: Annotated[dict[str, dict], Reducers.merge_dicts]  # spec_id → InteractiveComponent
    widget_kinds: Annotated[
        dict[str, str], Reducers.merge_dicts
    ]  # spec_id → kind actually built (media → svg fallback)
    alignment: dict | None  # AlignmentReport

    # Stage C
    page_code: Annotated[dict[str, str], Reducers.merge_dicts]
    component_code: Annotated[dict[str, str], Reducers.merge_dicts]  # component name → checked TSX
    document_code: str | None
    render_report: dict | None

    # control
    attempts: Annotated[dict[str, int], Reducers.merge_counts]
    feedback: Annotated[dict[str, list[str]], Reducers.merge_dicts]
    warnings: Annotated[list[str], operator.add]
    failed_node: str | None  # where await_retry resumes
    retry_keys: list[str]  # attempt counters reset on retry
    error: str | None
    extra_material: bool  # the study_material graph (another sheet later), not the main flow


class Branch(TypedDict, total=False):
    """Input of a `Send` branch: the item to work on plus the shared context it needs."""

    key: str
    item: Any
    feedback: list[str]
    lesson_id: str
    topic: str
    profile: dict
    snapshot: dict
    settings: dict
    assessment: dict
    plan: dict
    pages: dict
    interactive_plan: dict
    media: dict
    prerequisites_to_cover: list[dict]

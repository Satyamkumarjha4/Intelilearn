"""Helpers shared by the nodes: lesson updates, validation outcomes, and the failure/retry pair."""

from django.utils import timezone
from langgraph.types import Command, interrupt

from lessons.models import Lesson, Stage

from ..context import emit, node_settings


def update_lesson(lesson_id: str, **fields) -> None:
    Lesson.objects.filter(pk=lesson_id).update(updated_at=timezone.now(), **fields)


def set_stage(lesson_id: str, stage: Stage, **fields) -> None:
    update_lesson(lesson_id, stage=stage, error="", **fields)


def learner_profile(profile) -> dict:
    """LearnerProfile: the parts of accounts.Profile that shape the content (no name or email)."""
    return {
        "education_level": profile.get_education_level_display() if profile.education_level else "",
        "grade_or_year": profile.grade_or_year,
        "field_of_study": profile.field_of_study,
        "preferred_language": profile.preferred_language or "en",
        "learning_preference": profile.learning_preference,
        "goal": profile.get_goal_display() if profile.goal else "",
        "notes": profile.notes,
    }


def outcome(state: dict, key: str, node_key: str, problems: list[str], retry_node: str, label: str) -> dict:
    """Record a validation result. When attempts run out, set `error` so the router goes to mark_failed."""
    update: dict = {"feedback": {key: problems}}
    if not problems:
        return update
    attempts = (state.get("attempts") or {}).get(key, 0)
    if attempts >= node_settings(state, node_key)["max_attempts"]:
        summary = "; ".join(problems[:4]) + (" …" if len(problems) > 4 else "")
        update |= {"error": f"{label} still failed its checks after {attempts} attempts: {summary}",
                   "failed_node": retry_node, "retry_keys": [key]}  # fmt: skip
    else:
        emit({"type": "attempt", "node": retry_node, "attempt": attempts + 1, "reason": problems[0]})
    return update


def route_check(state: dict, key: str, *, ok: str, retry: str) -> str:
    if not (state.get("feedback") or {}).get(key):
        return ok
    return "mark_failed" if state.get("error") else retry


def mark_failed(state: dict) -> dict:
    """Side effects of a failure; `await_retry` (after it) only pauses, because it re-runs on resume."""
    message = state.get("error") or "The lesson could not be built."
    update_lesson(state["lesson_id"], stage=Stage.FAILED, error=message)
    emit({"type": "failed", "message": message})
    return {}


def await_retry(state: dict) -> Command:
    """Paused until POST /lessons/{id}/retry resumes the thread, then re-runs the node that gave up."""
    interrupt({"kind": "retry"})
    keys = state.get("retry_keys") or []
    return Command(
        goto=state.get("failed_node") or "load_context",
        update={
            "error": None,
            "failed_node": None,
            "retry_keys": [],
            "attempts": dict.fromkeys(keys),  # None resets the count (merge_counts)
        },
    )

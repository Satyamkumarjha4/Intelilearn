"""`Send` branches: the input of one parallel item (a page, a widget, a fix) is the shared context plus the item."""

from typing import Any

#: What every branch needs from the lesson's state to call a model and to see the whole plan.
SHARED_KEYS = (
    "lesson_id", "topic", "user_context", "profile", "snapshot", "settings", "assessment", "plan", "pages",
    "interactive_plan", "media", "prerequisites_to_cover", "final_test",
)  # fmt: skip


class BranchBuilder:
    @staticmethod
    def of(state: dict, **extra: Any) -> dict:
        """The shared context from `state` plus what this branch works on (`key`, `item`, `feedback`…)."""
        return {key: state.get(key) for key in SHARED_KEYS} | extra

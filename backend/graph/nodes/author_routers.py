"""Stage B's conditional edges: they turn the join nodes' bookkeeping into the next `Send`s or node."""

from langgraph.types import Send

from ..alignment import AlignmentPolicy
from .author import AuthoringStatus, WidgetStatus
from .branches import BranchBuilder
from .routers import CheckRouter, Router


class PlanRouter(Router):
    """After validate_plan: fan out the pages and the test, retry the plan, or give up."""

    def __call__(self, state: dict):
        target = CheckRouter("plan", ok="fan_out", retry="plan_lesson")(state)
        return AuthoringStatus.sends(state) if target == "fan_out" else target


class AuthoringRouter(Router):
    """After authored_join: send only the pages (or the test) that still need work, else on to the interactives."""

    def __call__(self, state: dict):
        retry, _ = AuthoringStatus.of(state)
        return AuthoringStatus.sends(state, keys=retry) if retry else "plan_interactives"


class InteractivePlanRouter(Router):
    """After validate_interactive_plan: plan again, or build every spec in parallel (media or code)."""

    def __call__(self, state: dict):
        if (state.get("feedback") or {}).get("interactive_plan"):
            return "plan_interactives"
        return WidgetStatus.sends(state) or "widgets_join"


class WidgetRouter(Router):
    """After widgets_join: send only the widgets that failed, else on to the alignment judge."""

    def __call__(self, state: dict):
        retry, _ = WidgetStatus.of(state)
        return WidgetStatus.sends(state, spec_ids=set(retry)) if retry else "alignment_judge"


class AlignmentRouter(Router):
    """After the judge: fix only the flagged items (in parallel), fail, or go on to the build."""

    def __init__(self, on_pass: str, on_fail: str = "mark_failed"):
        self.on_pass, self.on_fail = on_pass, on_fail

    def __call__(self, state: dict):
        report = state["alignment"]
        if report["decision"] == "fix":
            fixable = AlignmentPolicy.fixable(state, report["issues"])
            return [
                Send("fix_item", BranchBuilder.of(state, key=f"{i['target']}:{i['target_id']}", item=i, feedback=[]))
                for i in fixable
            ]
        return self.on_fail if report["decision"] == "fail" else self.on_pass

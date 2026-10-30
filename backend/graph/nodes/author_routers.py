"""Stage B's conditional edges: they turn the join nodes' bookkeeping into the next `Send`s or node."""

from langgraph.types import Send

from ..alignment import AlignmentPolicy
from .author import AuthoringStatus, WidgetStatus
from .branches import BranchBuilder
from .questions import QuestionRound, QuestionSends
from .routers import CheckRouter, Router


class PlanRouter(Router):
    """After validate_plan: plan the test's batches, retry the plan, or give up."""

    def __call__(self, state: dict):
        target = CheckRouter("plan", ok="plan_batches", retry="plan_lesson")(state)
        return target


class BatchesRouter(Router):
    """After plan_batches: the first round writes the three pages and every batch of the test at once; a later round
    (cells that are still unfilled) writes only the batches."""

    def __call__(self, state: dict):
        sends = QuestionSends.of(state)
        if state["question_plan"]["round"] == 1:
            sends = AuthoringStatus.sends(state) + sends
        return sends


class AuthoringRouter(Router):
    """After authored_join: send only what still needs work (pages, or batches of the test), plan the test's unfilled
    cells again, fail when the test cannot be filled, wait while a batch is still being written, else on to the
    interactives."""

    def __init__(self, on_fail: str = "mark_failed", questions: QuestionRound | None = None):
        self.on_fail = on_fail
        self.questions = questions or QuestionRound()

    def __call__(self, state: dict):
        outcome = state.get("question_outcome")
        if outcome == QuestionRound.SHORT:
            return self.on_fail
        if outcome == QuestionRound.REPLAN:
            return "plan_batches"
        if outcome == QuestionRound.PENDING:
            return []
        retry, _ = AuthoringStatus.of(state)
        sends = AuthoringStatus.sends(state, keys=retry)
        if outcome == QuestionRound.RETRY:
            sends += QuestionSends.of(state, set(self.questions.retry_ids(state)))
        return sends or "plan_interactives"


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

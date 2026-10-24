"""The alignment judge's decision, made in code: the model's own verdict is not trusted."""

from dataclasses import dataclass
from typing import Literal

from .schemas import PAGE_KEYS, AlignmentReport

Decision = Literal["pass", "fix", "accept", "fail"]


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    report: dict  # the report with `passed`, `round` and `decision` filled in
    fixable: list[dict]  # the issues to send back (one per item), when the decision is `fix`
    warnings: list[str]
    error: str = ""


class AlignmentPolicy:
    """pass → on; issues and rounds left → fix only the flagged items; rounds out with only minor issues → accept with
    a warning; rounds out with a major issue → fail."""

    def decide(self, report: AlignmentReport, *, state: dict, round_number: int) -> Verdict:
        settings = state["settings"]
        passed = report.recompute_passed(settings.get("alignment_min_score", 3))
        data = report.model_dump(mode="json") | {"passed": passed, "round": round_number}
        issues = data["issues"]
        fixable = self.fixable(state, issues)
        if passed:
            data["decision"] = "pass"
            return Verdict("pass", data, [], [f"Content review note: {i['problem']}" for i in issues][:5])
        if round_number <= settings.get("alignment_max_rounds", 2) and fixable:
            data["decision"] = "fix"
            return Verdict("fix", data, fixable, [])
        majors = [i["problem"] for i in issues if i["severity"] == "major"]
        if not majors:
            data["decision"] = "accept"
            remaining = "; ".join(i["problem"] for i in issues[:3]) or "some scores are below the threshold"
            return Verdict("accept", data, [], [f"Content review: minor issues remain: {remaining}"])
        data["decision"] = "fail"
        error = "The content review found problems it could not fix: " + "; ".join(majors[:3])
        return Verdict("fail", data, [], [], error)

    @staticmethod
    def fixable(state: dict, issues: list[dict]) -> list[dict]:
        """One issue per item, and only for items that exist (the judge may name a page or widget that does not)."""
        specs = {s["id"] for s in (state.get("interactive_plan") or {}).get("specs", [])}
        fixable, seen = [], set()
        for issue in issues:
            target, target_id = issue["target"], issue["target_id"]
            if target == "page" and target_id not in PAGE_KEYS:
                continue
            if target in ("interactive", "media") and target_id not in specs:
                continue
            slot = ("final_test", "") if target == "final_test" else (target, target_id)
            if slot not in seen:
                seen.add(slot)
                fixable.append(issue)
        return fixable

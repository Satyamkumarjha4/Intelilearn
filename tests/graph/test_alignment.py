"""Unit under test: `graph.alignment.AlignmentPolicy`, which turns the alignment judge's report into a decision.

Why: it is the quality gate before any code is generated. The model's own `passed` flag is not trusted, so this is
where "good enough" is defined: a lesson with a wrong fact must not slip through because the judge was generous, and a
lesson with a cosmetic issue must not be failed for it.

Use cases:
- every score at or above the minimum and no major issue passes (the judge's own flag is ignored); notes become warnings
- a failing report with rounds left and fixable issues is sent back to fix, one issue per item
- issues naming a page, widget or media that does not exist are not fixable
- out of rounds with only minor issues the lesson is accepted with a warning
- out of rounds with a major issue the run fails with the problems named
- a low score with no issues at all, out of rounds, is accepted (nothing to fix and nothing major)
- the minimum score and the number of rounds come from the lesson's settings
"""

import pytest
from support.lesson_data import make_state

from graph.alignment import AlignmentPolicy
from graph.schemas import AlignmentReport

policy = AlignmentPolicy()


def report(scores=5, issues=(), passed=True) -> AlignmentReport:
    values = scores if isinstance(scores, dict) else dict.fromkeys(AlignmentReport.SCORE_FIELDS, scores)
    return AlignmentReport(**values, issues=list(issues), passed=passed)


def issue(target="page", target_id="core", severity="minor", problem="p"):
    return {
        "target": target,
        "target_id": target_id,
        "severity": severity,
        "problem": problem,
        "fix_instruction": "fix it",
    }


def decide(rep, round_number=1, **settings):
    state = make_state(settings={"alignment_min_score": 3, "alignment_max_rounds": 2} | settings)
    return policy.decide(rep, state=state, round_number=round_number)


def test_passes_when_scores_are_high_and_nothing_is_major_ignoring_the_judges_own_flag():
    verdict = decide(report(4, [issue(problem="a typo")], passed=False))

    assert verdict.decision == "pass" and verdict.report["passed"] is True
    assert verdict.warnings == ["Content review note: a typo"] and verdict.report["round"] == 1


def test_the_judges_generosity_does_not_pass_a_major_issue():
    verdict = decide(report(5, [issue(severity="major", problem="wrong fact")], passed=True), round_number=3)

    assert verdict.decision == "fail" and "wrong fact" in verdict.error


@pytest.mark.parametrize("low", [1, 2])
def test_a_score_below_the_minimum_does_not_pass(low):
    scores = {name: 5 for name in AlignmentReport.SCORE_FIELDS} | {"level_fit": low}

    assert decide(report(scores, [issue()])).decision == "fix"


def test_a_failing_report_with_rounds_left_is_sent_back_one_issue_per_item():
    issues = [issue("page", "core", "major"), issue("page", "core", "minor", "second"), issue("final_test", "t3"),
              issue("interactive", "widget_core")]  # fmt: skip

    verdict = decide(report(2, issues))

    assert verdict.decision == "fix"
    assert [(i["target"], i["target_id"]) for i in verdict.fixable] == [
        ("page", "core"), ("final_test", "t3"), ("interactive", "widget_core"),
    ]  # fmt: skip


def test_issues_for_items_that_do_not_exist_are_not_fixable():
    issues = [issue("page", "nonsense", "major"), issue("interactive", "ghost"), issue("media", "ghost2")]

    verdict = decide(report(2, issues), round_number=1)

    assert verdict.fixable == [] and verdict.decision == "fail"


def test_out_of_rounds_with_only_minor_issues_is_accepted_with_a_warning():
    verdict = decide(report(2, [issue(problem="tone is dry")]), round_number=3)

    assert verdict.decision == "accept" and verdict.warnings == ["Content review: minor issues remain: tone is dry"]


def test_out_of_rounds_with_a_major_issue_fails_naming_the_problems():
    issues = [
        issue(severity="major", problem="Wrong complexity"),
        issue(severity="major", problem="Missing prerequisite"),
    ]

    verdict = decide(report(2, issues), round_number=3)

    assert verdict.decision == "fail"
    assert verdict.error == (
        "The content review found problems it could not fix: Wrong complexity; Missing prerequisite"
    )


def test_a_low_score_with_no_issues_and_no_rounds_left_is_accepted():
    verdict = decide(report(2, []), round_number=3)

    assert verdict.decision == "accept" and "some scores are below the threshold" in verdict.warnings[0]


def test_the_minimum_score_and_the_rounds_come_from_the_settings():
    assert decide(report(3), alignment_min_score=4).decision == "accept"  # nothing to fix, nothing major
    assert decide(report(3, [issue()]), alignment_min_score=4, alignment_max_rounds=1).decision == "fix"
    assert (
        decide(report(3, [issue()]), round_number=2, alignment_min_score=4, alignment_max_rounds=1).decision == "accept"
    )

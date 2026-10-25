"""Unit under test: `onboarding.reasons.ReasonBuilder`, the short line under each suggested topic that says why it is
there.

Why: the line is what makes a list of topics feel chosen for the learner. It has to be true (never "in your Class 9
syllabus" for someone who gave no class) and it has to read well with or without the details they gave.

Use cases:
- exam preparation names the class or year when there is one ("Class 9 · often in exams"), and says "Often in exams"
  without
- interview preparation says "Common in interviews"
- school says "In your Class 9 syllabus", or "Popular with students" when there is no class
- self-learners are "Popular with self-learners", professionals "Useful at work", everyone else "Picked for your course"
- the first rule that applies wins, in that order (exam preparation beats school)
"""

import pytest

from onboarding.domain import SuggestionRequest
from onboarding.reasons import ReasonBuilder


def reason(**fields):
    return ReasonBuilder().reason(
        SuggestionRequest(**{"education_level": "school", "goal": "deep_understanding", **fields})
    )


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"goal": "exam_prep", "grade_or_year": "9th"}, "Class 9 · often in exams"),
        (
            {"goal": "exam_prep", "education_level": "undergraduate", "grade_or_year": "2nd year B.Tech"},
            "2nd year B.Tech · often in exams",
        ),
        ({"goal": "exam_prep", "education_level": "undergraduate"}, "Often in exams"),
        ({"goal": "interview_prep", "education_level": "professional"}, "Common in interviews"),
        ({"grade_or_year": "Class 9"}, "In your Class 9 syllabus"),
        ({"grade_or_year": ""}, "Popular with students"),
        ({"education_level": "self_learner"}, "Popular with self-learners"),
        ({"education_level": "professional"}, "Useful at work"),
        ({"education_level": "undergraduate"}, "Picked for your course"),
        ({"education_level": "postgraduate"}, "Picked for your course"),
    ],
)
def test_the_reason_reads_from_what_the_learner_said(fields, expected):
    assert reason(**fields) == expected


def test_the_first_rule_that_applies_wins():
    assert reason(goal="exam_prep", grade_or_year="Class 9") == "Class 9 · often in exams"
    assert reason(goal="interview_prep", grade_or_year="Class 9") == "Common in interviews"

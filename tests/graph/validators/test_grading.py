"""Unit under test: `graph.validators.GradeReportValidator`, the checks on the marks a model gave for the open-ended
answers of a test.

Why: the model's marks become the learner's score. A missing grade leaves a question ungraded, a mark above the
question's worth inflates the total, and a duplicate would be counted twice. Each problem is sent back to the model as
feedback, so it must say what to change.

Use cases:
- a grade for every question sent, each once, within its marks and with feedback, passes
- a missing grade, an id that was not asked about, a repeated id, marks above the question's worth, and blank
  feedback are each reported by question id
- several problems are all reported at once
"""

from graph.validators import GradeReportValidator

QUESTIONS = [{"id": "s1", "marks": 4}, {"id": "c1", "marks": 5}]
validate = GradeReportValidator().validate


def report(*grades):
    return {
        "grades": [{"question_id": qid, "awarded": awarded, "feedback": feedback} for qid, awarded, feedback in grades]
    }


def test_a_complete_grading_within_the_marks_passes():
    assert validate(report(("s1", 4, "Good."), ("c1", 0, "No logic.")), questions=QUESTIONS) == []


def test_a_missing_grade_is_named():
    assert validate(report(("s1", 4, "Good.")), questions=QUESTIONS) == ["Grade every question; these are missing: c1."]


def test_an_id_that_was_not_asked_about_is_named():
    problems = validate(report(("s1", 1, "a"), ("c1", 1, "b"), ("zz", 1, "c")), questions=QUESTIONS)

    assert problems == ["These ids were not asked about: zz."]


def test_a_question_graded_twice_is_named():
    problems = validate(report(("s1", 1, "a"), ("s1", 2, "b"), ("c1", 1, "c")), questions=QUESTIONS)

    assert problems == ["Grade each question once; these appear more than once: s1."]


def test_marks_above_the_questions_worth_are_reported():
    assert validate(report(("s1", 5, "a"), ("c1", 5, "b")), questions=QUESTIONS) == [
        "s1: awarded 5 but the question is worth 4."
    ]


def test_blank_feedback_is_reported():
    assert validate(report(("s1", 2, "  "), ("c1", 1, "ok")), questions=QUESTIONS) == [
        "s1: write feedback for the learner."
    ]


def test_every_problem_is_reported_at_once():
    problems = validate(report(("s1", 9, ""), ("zz", 1, "x")), questions=QUESTIONS)

    assert len(problems) == 4

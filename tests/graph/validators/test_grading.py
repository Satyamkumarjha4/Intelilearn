"""Unit under test: `graph.validators.GradeReportValidator`, the checks on the marks a model gave, criterion by
criterion, for the open-ended answers of a test.

Why: the model's marks become the learner's score. A missing grade leaves a question ungraded, an award above its
criterion inflates the total, a fraction or a negative number cannot be explained, and a duplicate would be counted
twice. Each problem is sent back to the model as feedback, so it must say what to change.

Use cases:
- a grade for every question sent, each once, with one whole award per criterion within that criterion's marks, and
  feedback, passes
- a missing grade, an id that was not asked about, a repeated id and blank feedback are each reported by question id
- the wrong number of awards, an award above its criterion, a fractional or negative award are each reported
- awards that together exceed the question's marks are reported
- several problems are all reported at once
"""

from graph.validators import GradeReportValidator

QUESTIONS = [
    {"id": "s1", "marks": 3, "criteria": [{"text": "a", "marks": 1}, {"text": "b", "marks": 2}]},
    {"id": "c1", "marks": 5, "criteria": [{"text": "c", "marks": 5}]},
]
validate = GradeReportValidator().validate


def report(*grades):
    return {
        "grades": [{"question_id": qid, "awards": awards, "feedback": feedback} for qid, awards, feedback in grades]
    }


def test_a_complete_grading_within_the_criteria_passes():
    assert validate(report(("s1", [1, 2], "Good."), ("c1", [0], "No logic.")), questions=QUESTIONS) == []


def test_a_missing_grade_is_named():
    assert validate(report(("s1", [1, 2], "Good.")), questions=QUESTIONS) == [
        "Grade every question; these are missing: c1."
    ]


def test_an_id_that_was_not_asked_about_is_named():
    problems = validate(report(("s1", [1, 1], "a"), ("c1", [1], "b"), ("zz", [1], "c")), questions=QUESTIONS)

    assert problems == ["These ids were not asked about: zz."]


def test_a_question_graded_twice_is_named():
    problems = validate(report(("s1", [1, 1], "a"), ("s1", [0, 0], "b"), ("c1", [1], "c")), questions=QUESTIONS)

    assert problems == ["Grade each question once; these appear more than once: s1."]


def test_blank_feedback_is_reported():
    assert validate(report(("s1", [1, 1], "  "), ("c1", [1], "ok")), questions=QUESTIONS) == [
        "s1: write feedback for the learner."
    ]


def test_the_wrong_number_of_awards_is_reported():
    problems = validate(report(("s1", [3], "a"), ("c1", [1, 1], "b")), questions=QUESTIONS)

    assert problems == [
        "s1: give 2 awards, one per criterion in order; there are 1.",
        "c1: give 1 awards, one per criterion in order; there are 2.",
    ]


def test_an_award_above_its_criterion_is_reported_by_position():
    assert validate(report(("s1", [1, 3], "a"), ("c1", [5], "b")), questions=QUESTIONS) == [
        "s1: award 2 is 3 but that criterion is worth 2."
    ]


def test_a_fractional_negative_or_non_numeric_award_is_reported():
    problems = validate(report(("s1", [0.5, -1], "a"), ("c1", ["5"], "b")), questions=QUESTIONS)

    assert problems == [
        "s1: award 1 must be a whole number, 0 or more.",
        "s1: award 2 must be a whole number, 0 or more.",
        "c1: award 1 must be a whole number, 0 or more.",
    ]


def test_a_true_or_false_is_not_a_whole_number():
    assert validate(report(("s1", [True, 2], "a"), ("c1", [5], "b")), questions=QUESTIONS) == [
        "s1: award 1 must be a whole number, 0 or more."
    ]


def test_awards_that_together_exceed_the_questions_marks_are_reported():
    questions = [{"id": "q", "marks": 2, "criteria": [{"text": "a", "marks": 2}, {"text": "b", "marks": 2}]}]

    assert validate(report(("q", [2, 2], "a")), questions=questions) == ["q: awarded 4 but the question is worth 2."]


def test_every_problem_is_reported_at_once():
    problems = validate(report(("s1", [9], ""), ("zz", [1], "x")), questions=QUESTIONS)

    assert len(problems) == 4

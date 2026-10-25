"""The marks a model gave for the open-ended answers of a test."""

from collections import Counter


class GradeReportValidator:
    """Every answer sent for grading is graded once, within its marks, with feedback the learner can read."""

    def validate(self, report: dict, *, questions: list[dict]) -> list[str]:
        marks = {q["id"]: q["marks"] for q in questions}
        grades = report["grades"]
        problems = []
        counts = Counter(g["question_id"] for g in grades)
        if missing := [qid for qid in marks if qid not in counts]:
            problems.append(f"Grade every question; these are missing: {', '.join(missing)}.")
        if unknown := sorted(set(counts) - set(marks)):
            problems.append(f"These ids were not asked about: {', '.join(unknown)}.")
        if repeated := sorted(qid for qid, n in counts.items() if n > 1):
            problems.append(f"Grade each question once; these appear more than once: {', '.join(repeated)}.")
        for grade in grades:
            qid = grade["question_id"]
            if qid in marks and grade["awarded"] > marks[qid]:
                problems.append(f"{qid}: awarded {grade['awarded']} but the question is worth {marks[qid]}.")
            if not grade["feedback"].strip():
                problems.append(f"{qid}: write feedback for the learner.")
        return problems

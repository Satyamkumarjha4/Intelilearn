"""The marks a model gave, criterion by criterion, for the open-ended answers of a test."""

from collections import Counter


class GradeReportValidator:
    """Every answer sent for grading is graded once, one whole number per criterion, no criterion above its marks,
    with feedback the learner can read."""

    def validate(self, report: dict, *, questions: list[dict]) -> list[str]:
        by_id = {q["id"]: q for q in questions}
        grades = report["grades"]
        problems = []
        counts = Counter(g["question_id"] for g in grades)
        if missing := [qid for qid in by_id if qid not in counts]:
            problems.append(f"Grade every question; these are missing: {', '.join(missing)}.")
        if unknown := sorted(set(counts) - set(by_id)):
            problems.append(f"These ids were not asked about: {', '.join(unknown)}.")
        if repeated := sorted(qid for qid, n in counts.items() if n > 1):
            problems.append(f"Grade each question once; these appear more than once: {', '.join(repeated)}.")
        for grade in grades:
            qid = grade["question_id"]
            if qid in by_id:
                problems += self._awards(qid, grade["awards"], by_id[qid])
            if not grade["feedback"].strip():
                problems.append(f"{qid}: write feedback for the learner.")
        return problems

    @staticmethod
    def _awards(qid: str, awards: list, question: dict) -> list[str]:
        criteria = question["criteria"]
        if len(awards) != len(criteria):
            return [f"{qid}: give {len(criteria)} awards, one per criterion in order; there are {len(awards)}."]
        problems = []
        for number, (award, criterion) in enumerate(zip(awards, criteria, strict=True), start=1):
            if type(award) is not int or award < 0:
                problems.append(f"{qid}: award {number} must be a whole number, 0 or more.")
            elif award > criterion["marks"]:
                problems.append(f"{qid}: award {number} is {award} but that criterion is worth {criterion['marks']}.")
        if not problems and (total := sum(awards)) > question["marks"]:
            problems.append(f"{qid}: awarded {total} but the question is worth {question['marks']}.")
        return problems

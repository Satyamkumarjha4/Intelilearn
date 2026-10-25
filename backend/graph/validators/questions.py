"""Rules for test questions, shared by the final test and the practice sheet."""

import ast

from .base import TextRules


class QuestionRules:
    @classmethod
    def problems(cls, questions: list[dict], label: str = "Question") -> list[str]:
        problems = []
        if dupes := TextRules.duplicates(q["id"] for q in questions):
            problems.append(f"Question ids must be unique (repeated: {', '.join(dupes)}).")
        if dupes := TextRules.duplicates(TextRules.norm(q["question"]) for q in questions):
            problems.append(f"Questions must not repeat ({len(dupes)} repeated).")
        for q in questions:
            if q["type"] == "mcq":
                problems += TextRules.option_problems(f"{label} {q['id']}", q["options"])
            if q["type"] == "code" and (q.get("language") or "").lower() == "python" and q.get("reference_solution"):
                problems += cls.python_problems(f"{label} {q['id']} reference solution", q["reference_solution"])
        return problems

    @staticmethod
    def python_problems(label: str, code: str) -> list[str]:
        try:
            ast.parse(code)
        except SyntaxError as exc:
            return [f"{label} is not valid Python: {exc.msg} (line {exc.lineno})."]
        return []

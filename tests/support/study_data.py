"""Builders for schema-valid study sheets (the mastery path), as the graph stores them: dumped Pydantic models, so a
builder that drifts from the schema fails loudly. Each passes `StudyMaterialValidator` for `CONCEPTS`."""

from graph.schemas import CheatSheet, PracticeSheet, RevisionSheet
from graph.schemas.lesson import DIFFICULTIES

CONCEPTS = ["Halving the range", "Time complexity"]


def make_cheat_sheet() -> dict:
    items = [
        {
            "label": f"Item {n}",
            "kind": "formula" if n == 1 else "rule",
            "content": f"Remember the rule about {CONCEPTS[n % 2].lower()} number {n}.",
            "formula": "\\log_2 n" if n == 1 else "",
            "variables": [{"symbol": "n", "meaning": "number of items"}] if n == 1 else [],
            "when_to_use": "When the data is sorted.",
        }
        for n in range(1, 5)
    ]
    sections = [
        {"heading": f"{CONCEPTS[0]} and {CONCEPTS[1]}", "items": items},
        {"heading": "Pitfalls", "items": [{**item, "label": f"Pitfall {n}"} for n, item in enumerate(items[:3])]},
    ]
    return CheatSheet(
        title="Binary search cheat sheet", summary="The rules on one page.", sections=sections
    ).model_dump(mode="json")


def make_revision_sheet() -> dict:
    subtopics = [
        {
            "title": f"{CONCEPTS[n % 2]} {n}",
            "summary": f"A full paragraph about {CONCEPTS[n % 2].lower()} that explains the idea, why it matters, " * 3,
            "key_points": ["First point", "Second point", "Third point"],
            "worked_examples": [
                {"problem": "Find 7 in [1, 3, 7].", "solution": "Check the middle, then the right half."}
            ],
            "common_mistakes": ["Off by one at the boundary."],
        }
        for n in range(1, 5)
    ]
    return RevisionSheet(
        title="Binary search revision", overview="Everything in order.", subtopics=subtopics, final_tips=["Practise."]
    ).model_dump(mode="json")


def make_practice_sheet(count: int = 15) -> dict:
    """`count` questions: mcq, numerical and short_answer in turn, easy first."""
    kinds = ["mcq", "numerical", "short_answer"]
    questions = []
    for n in range(1, count + 1):
        kind = kinds[(n - 1) % 3]
        base = {
            "id": f"t{n}",
            "type": kind,
            "concept": CONCEPTS[n % 2],
            "difficulty": DIFFICULTIES[min(2, (n - 1) * 3 // count)],
            "marks": 2,
            "question": f"Practice question {n} about {CONCEPTS[n % 2].lower()}?",
        }
        extra = {
            "mcq": {"options": [f"Choice {c} {n}" for c in "ABCD"], "correct_index": n % 4},
            "numerical": {"answer": 4.0, "tolerance": 0.01, "unit": "steps"},
            "short_answer": {"model_answer": "Halve the range.", "key_points": ["halving"]},
        }[kind]
        questions.append({**base, **extra})
    return PracticeSheet(title="Binary search practice", instructions="Try each one.", questions=questions).model_dump(
        mode="json"
    )

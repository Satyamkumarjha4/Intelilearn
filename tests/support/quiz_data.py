"""Builders for well-formed quiz data in the shape the graph stores (plain JSON dicts)."""

from graph.schemas.diagnostic import BANDS

DEFAULT_SETTINGS = {
    "diagnostic_questions_per_band": 2,
    "prerequisite_question_count": 5,
    "prereq_trigger_max_correct": 2,
    "mastery_requires_all_correct": True,
}


def question(qid: str, band: str, concept: str, *, correct_index: int = 0) -> dict:
    return {
        "id": qid,
        "band": band,
        "concept": concept,
        "question": f"What is true about {concept}?",
        "options": [f"{concept} option {n}" for n in "ABCD"],
        "correct_index": correct_index,
        "explanation": f"Because of {concept}.",
    }


def make_questions(per_band: int = 2) -> list[dict]:
    return [
        question(f"q{index * per_band + n + 1}", band, f"concept {band} {n}")
        for index, band in enumerate(BANDS)
        for n in range(per_band)
    ]


def make_prerequisites(count: int = 5) -> tuple[list[dict], list[dict]]:
    prerequisites = [{"name": f"Prerequisite {n}", "why_needed": f"Needed for {n}."} for n in range(1, count + 1)]
    questions = [
        {
            "id": f"p{n}",
            "prerequisite": f"Prerequisite {n}",
            "question": f"Which statement about prerequisite number {n} holds?",
            "options": [f"prerequisite {n} choice {c}" for c in "ABCD"],
            "correct_index": 1,
            "explanation": f"Prerequisite {n} works like that.",
        }
        for n in range(1, count + 1)
    ]
    return prerequisites, questions

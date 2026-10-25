"""Builders for schema-valid lesson content (plan, pages, test, interactive plan…) as the graph stores it: plain JSON
dicts made by dumping the Pydantic models, so a builder that drifts from the schema fails loudly.

The default topic is "Binary search". Page bodies are long enough, and mention each outline concept, so they pass
`PageValidator`.
"""

from graph.schemas import (
    FinalTest,
    InteractivePlan,
    LearnerAssessment,
    LessonPlan,
    PageContent,
    TestQuestion,
)
from graph.schemas.lesson import PAGE_KEYS

CONCEPTS = {
    "introduction": ["Searching a list", "Sorted data", "Why halving helps"],
    "core": ["Halving the range", "The loop invariant", "Returning the index"],
    "advanced": ["Time complexity", "Off-by-one pitfalls", "Searching on answers"],
}
TYPE_MIX = {"mcq": 4, "numerical": 2, "short_answer": 2, "long_answer": 1, "code": 1}
DIFFICULTY_MIX = {"easy": 4, "medium": 4, "hard": 2}


def make_assessment(to_cover: list[str] = ()) -> dict:
    return LearnerAssessment(
        level="beginner",
        known_concepts=["Searching a list"],
        gaps=["The loop invariant"],
        prerequisites_to_cover=list(to_cover),
        start_point="Halving the range",
        author_notes="Short sentences, concrete examples.",
        confidence="medium",
    ).model_dump(mode="json")


def make_plan(prerequisites: list[str] = ()) -> dict:
    pages = [
        {
            "key": key,
            "title": f"{key.title()} page",
            "goals": ["Understand the idea", "Apply it once"],
            "outline": [{"concept": c, "heading": c, "notes": f"Explain {c}."} for c in CONCEPTS[key]],
            "covers_gaps": ["The loop invariant"] if key == "core" else [],
            "covers_prerequisites": list(prerequisites) if key == "introduction" else [],
        }
        for key in PAGE_KEYS
    ]
    return LessonPlan(
        title="Binary search",
        level="beginner",
        summary="Find a value in sorted data by halving the range. For beginners.",
        pages=pages,
        final_test={"question_count": 10, "type_mix": TYPE_MIX, "difficulty_mix": DIFFICULTY_MIX},
    ).model_dump(mode="json")


def make_page(key: str, plan: dict | None = None) -> dict:
    plan = plan or make_plan()
    page_plan = next(p for p in plan["pages"] if p["key"] == key)
    sections = [
        {
            "id": f"s{index}",
            "heading": item["heading"],
            "body": (
                f"{item['concept']} is the idea this section teaches. " * 6
                + "Work through it step by step with a small example and then try a second one yourself."
            ),
            "key_points": [f"Remember {item['concept']}."],
            "formulas": [{"latex": "\\log_2 n", "explanation": "Steps needed for n items."}] if index == 1 else [],
        }
        for index, item in enumerate(page_plan["outline"], start=1)
    ]
    return PageContent(key=key, title=page_plan["title"], sections=sections, summary=f"Recap of {key}.").model_dump(
        mode="json"
    )


def make_pages(plan: dict | None = None) -> dict:
    return {key: make_page(key, plan) for key in PAGE_KEYS}


def make_final_test(spec: dict | None = None) -> dict:
    spec = spec or make_plan()["final_test"]
    difficulties = [d for d, n in spec["difficulty_mix"].items() for _ in range(n)]
    questions, number = [], 0
    for kind, count in spec["type_mix"].items():
        for _ in range(count):
            number += 1
            base = {
                "id": f"t{number}",
                "type": kind,
                "concept": f"Concept {number}",
                "difficulty": difficulties[number - 1],
                "marks": 2,
                "question": f"Question number {number} about binary search?",
            }
            extra = {
                "mcq": {"options": [f"Choice {c} {number}" for c in "ABCD"], "correct_index": 1},
                "numerical": {"answer": 4.0, "tolerance": 0.01, "unit": "steps"},
                "short_answer": {"model_answer": "Halve the range.", "key_points": ["halving"]},
                "long_answer": {"model_answer": "A full explanation.", "rubric": ["states the invariant"]},
                "code": {
                    "language": "python",
                    "starter_code": "def search(items, target):\n    pass\n",
                    "reference_solution": "def search(items, target):\n    return items.index(target)\n",
                    "test_cases": [{"input": "[1, 2, 3], 2", "expected_output": "1"}],
                },
            }[kind]
            questions.append(TestQuestion(**base, **extra))
    return FinalTest(questions=questions).model_dump(mode="json")


def make_interactive_plan(pages: dict | None = None) -> dict:
    pages = pages or make_pages()
    specs = [
        {
            "id": f"widget_{key}",
            "page": key,
            "anchor_section": pages[key]["sections"][0]["id"],
            "kind": "simulation" if key == "core" else "svg_diagram",
            "purpose": f"Shows the main idea of the {key} page better than text.",
            "description": "A stepping demo with low, mid and high pointers.",
        }
        for key in PAGE_KEYS
    ]
    return InteractivePlan(specs=specs).model_dump(mode="json")


def make_state(**overrides) -> dict:
    """A graph state far enough along for every prompt and node of Stage B to read from."""
    plan = make_plan()
    pages = make_pages(plan)
    state = {
        "lesson_id": "00000000-0000-0000-0000-000000000001",
        "topic": "Binary search",
        "user_context": "for my DSA exam",
        "profile": {"education_level": "Undergraduate", "goal": "Exam prep", "preferred_language": "en"},
        "settings": {"final_test_min": 10, "final_test_max": 15, "max_interactives_per_page": 3},
        "assessment": make_assessment(),
        "prerequisites_to_cover": [],
        "plan": plan,
        "pages": pages,
        "final_test": make_final_test(plan["final_test"]),
        "interactive_plan": make_interactive_plan(pages),
    }
    return state | overrides

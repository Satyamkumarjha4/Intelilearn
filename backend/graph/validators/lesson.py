"""Stage B: the lesson plan, the content pages, the final test and the interactive plan."""

import re
from collections import Counter

from ..schemas.lesson import DIFFICULTIES, PAGE_KEYS, QUESTION_TYPES
from .base import LatexChecker, LatexRules, TextRules
from .questions import QuestionRules

norm = TextRules.norm


class PlanValidator:
    def validate(self, plan: dict, *, settings: dict, prerequisites_to_cover: list[dict]) -> list[str]:
        problems: list[str] = []
        keys = [page["key"] for page in plan["pages"]]
        if sorted(keys) != sorted(PAGE_KEYS):
            problems.append(f"Plan exactly three pages with keys {', '.join(PAGE_KEYS)} (got {', '.join(keys)}).")
        concepts = [norm(item["concept"]) for page in plan["pages"] for item in page["outline"]]
        if dupes := TextRules.duplicates(concepts):
            problems.append("Each concept belongs to one page only; repeated across pages: " + ", ".join(dupes))
        for page in plan["pages"]:
            if not 2 <= len(page["outline"]) <= 8:
                problems.append(f'Page "{page["key"]}" needs 2-8 outline parts; it has {len(page["outline"])}.')
        intro = next((p for p in plan["pages"] if p["key"] == "introduction"), None)
        covered = {norm(name) for name in (intro or {}).get("covers_prerequisites", [])}
        for prerequisite in prerequisites_to_cover:
            if norm(prerequisite["name"]) not in covered:
                problems.append(
                    f'The introduction must cover the prerequisite "{prerequisite["name"]}" (list it in '
                    "covers_prerequisites and teach it in the outline)."
                )
        return problems + self._test_spec(plan["final_test"], settings)

    @staticmethod
    def _test_spec(spec: dict, settings: dict) -> list[str]:
        problems = []
        low, high = settings.get("final_test_min", 10), settings.get("final_test_max", 15)
        count = spec["question_count"]
        if not low <= count <= high:
            problems.append(f"The final test must have {low}-{high} questions; the plan says {count}.")
        if (types := sum(spec["type_mix"].values())) != count:
            problems.append(f"type_mix adds up to {types}, not question_count {count}.")
        if (levels := sum(spec["difficulty_mix"].values())) != count:
            problems.append(f"difficulty_mix adds up to {levels}, not question_count {count}.")
        if sum(1 for n in spec["type_mix"].values() if n) < 3:
            problems.append("Mix at least 3 question types in the final test.")
        return problems


class PageValidator:
    def __init__(self, latex: LatexChecker | None = None):
        self.latex = LatexRules(latex)

    def validate(self, page: dict, *, plan_page: dict) -> list[str]:
        problems: list[str] = []
        sections = page["sections"]
        if page["key"] != plan_page["key"]:
            problems.append(f'This page must have key "{plan_page["key"]}".')
        if not 2 <= len(sections) <= 8:
            problems.append(f"Write 2-8 sections; there are {len(sections)}.")
        if dupes := TextRules.duplicates(s["id"] for s in sections):
            problems.append(f"Section ids must be unique (repeated: {', '.join(dupes)}).")
        if dupes := TextRules.duplicates(norm(s["heading"]) for s in sections):
            problems.append(f"Section headings must be unique (repeated: {', '.join(dupes)}).")
        for section in sections:
            if len(section["body"]) < 200:
                problems.append(f'Section "{section["heading"]}" is too thin: explain it in at least a paragraph.')
        text = " ".join(s["heading"] + " " + s["body"] for s in sections)
        missing = [item["concept"] for item in plan_page["outline"] if not TextRules.mentions(text, item["concept"])]
        if missing:
            problems.append("Teach every concept in the plan's outline; missing: " + "; ".join(missing))

        expressions = []
        for section in sections:
            expressions += TextRules.math_in(section["body"]) + [f["latex"] for f in section["formulas"]]
            expressions += [
                m for ex in section["worked_examples"] for part in ex.values() for m in TextRules.math_in(part)
            ]
            for snippet in section["code_snippets"]:
                if snippet["language"].lower() in ("python", "py"):
                    problems += QuestionRules.python_problems(f'The code in "{section["heading"]}"', snippet["code"])
        return problems + self.latex.problems(expressions)


class FinalTestValidator:
    def __init__(self, latex: LatexChecker | None = None):
        self.latex = LatexRules(latex)

    def validate(self, test: dict, *, spec: dict) -> list[str]:
        questions = test["questions"]
        problems = []
        if len(questions) != spec["question_count"]:
            problems.append(f"Write exactly {spec['question_count']} questions; there are {len(questions)}.")
        problems += self._mix(Counter(q["type"] for q in questions), spec["type_mix"], QUESTION_TYPES)
        problems += self._mix(Counter(q["difficulty"] for q in questions), spec["difficulty_mix"], DIFFICULTIES)
        problems += QuestionRules.problems(questions)
        return problems + self.latex.problems([m for q in questions for m in TextRules.math_in(q["question"])])

    @staticmethod
    def _mix(actual: Counter, wanted: dict, kinds: tuple[str, ...]) -> list[str]:
        return [
            f"Write exactly {wanted.get(kind, 0)} {kind} questions; there are {actual.get(kind, 0)}."
            for kind in kinds
            if actual.get(kind, 0) != wanted.get(kind, 0)
        ]


class InteractivePlanValidator:
    ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,40}")

    def validate(self, plan: dict, *, pages: dict, settings: dict) -> list[str]:
        problems: list[str] = []
        specs = plan["specs"]
        max_per_page = settings.get("max_interactives_per_page", 3)
        if dupes := TextRules.duplicates(s["id"] for s in specs):
            problems.append(f"Interactive ids must be unique (repeated: {', '.join(dupes)}).")
        for spec in specs:
            if not self.ID.fullmatch(spec["id"]):
                problems.append(f'Interactive id "{spec["id"]}" must be letters, digits and underscores.')
            page = pages.get(spec["page"])
            if page and spec["anchor_section"] not in {s["id"] for s in page["sections"]}:
                problems.append(
                    f'Interactive "{spec["id"]}" anchors to section "{spec["anchor_section"]}", which '
                    f"doesn't exist on the {spec['page']} page."
                )
            if spec["kind"] in ("image", "gif") and not spec.get("media_query", "").strip():
                problems.append(f'Interactive "{spec["id"]}" is an {spec["kind"]}: give it a media_query.')
            if len(spec["purpose"]) < 15:
                problems.append(f'Interactive "{spec["id"]}": say which concept it teaches in purpose.')
        for key in PAGE_KEYS:
            count = sum(1 for s in specs if s["page"] == key)
            if count == 0:
                problems.append(f"Give the {key} page at least one interactive.")
            if count > max_per_page:
                problems.append(f"The {key} page has {count} interactives; at most {max_per_page} are allowed.")
        return problems

"""Stage B: the lesson plan, the content pages, the questions of the test and the interactive plan."""

import re

from ..schemas.lesson import PAGE_KEYS
from ..shapes import LessonShape
from .base import LatexChecker, LatexRules, TextRules
from .questions import QuestionRules

norm = TextRules.norm


class PlanValidator:
    """The shape of the learner's level says which slots the plan has; the prerequisites the lesson was given are
    taught on the first page whatever the level (a quiz that found a gap made the promise)."""

    def validate(
        self, plan: dict, *, prerequisites_to_cover: list[dict], shape: LessonShape | None = None
    ) -> list[str]:
        problems: list[str] = []
        wanted = shape.page_keys if shape else PAGE_KEYS
        keys = [page["key"] for page in plan["pages"]]
        if sorted(keys) != sorted(wanted):
            problems.append(f"Plan exactly three pages with keys {', '.join(wanted)} (got {', '.join(keys)}).")
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


class QuestionBatchValidator:
    """The questions a model wrote for a list of cells: one for each cell, in order, of that cell's type and
    difficulty, and each a good question of its kind. The same rules check a batch of a lesson test, of a retake, and
    the one question written again after a review."""

    def __init__(self, latex: LatexChecker | None = None):
        self.latex = LatexRules(latex)

    def validate(self, questions: list[dict], *, cells) -> list[str]:
        problems = []
        if len(questions) != len(cells):
            problems.append(
                f"Write exactly {len(cells)} questions, one for each cell, in order; there are {len(questions)}."
            )
        for cell, question in zip(cells, questions, strict=False):
            if question["type"] != cell.type:
                problems.append(
                    f"Question {question['id']} must be a {cell.type} question; it is a {question['type']}."
                )
            if question["difficulty"] != cell.difficulty:
                problems.append(f"Question {question['id']} must be {cell.difficulty}; it is {question['difficulty']}.")
        problems += QuestionRules.problems(questions)
        return problems + self.latex.problems([m for q in questions for m in TextRules.math_in(q["question"])])


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

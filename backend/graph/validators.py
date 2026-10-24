"""Deterministic checks that follow every LLM step. Each returns a list of problems in plain language; an empty
list means valid. The problems go back to the model as feedback on the retry, so they say what to change.

Rules that JSON Schema can't express ("2 questions per band", "concepts unique") live here, not in the schemas.
"""

import ast
import re
from collections import Counter
from collections.abc import Callable, Iterable

from .schemas.diagnostic import BANDS
from .schemas.lesson import DIFFICULTIES, PAGE_KEYS, QUESTION_TYPES

LatexChecker = Callable[[list[str]], list[str]]  # returns one message per expression that doesn't parse

_CATCH_ALL = re.compile(r"\b(all|none|both|neither) of (the )?(above|these|them)\b|\ball the above\b", re.I)
_MATH = re.compile(r"\$\$(.+?)\$\$|\$([^$\n]+?)\$", re.S)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _duplicates(values: Iterable[str]) -> list[str]:
    return [value for value, count in Counter(values).items() if count > 1]


def math_in(text: str) -> list[str]:
    """LaTeX fragments inside $…$ / $$…$$ in a Markdown string."""
    return [(block or inline).strip() for block, inline in _MATH.findall(text or "")]


def _latex(checker: LatexChecker | None, expressions: list[str]) -> list[str]:
    expressions = [e for e in expressions if e]
    return checker(expressions) if checker and expressions else []


def _options_problems(label: str, options: list[str]) -> list[str]:
    problems = []
    if len({norm(o) for o in options}) != len(options):
        problems.append(f"{label}: options must all be different.")
    if any(_CATCH_ALL.search(o) for o in options):
        problems.append(f'{label}: don\'t use "all/none of the above" style options.')
    return problems


# --- Stage A -------------------------------------------------------------------------------------------------


def validate_diagnostic(bundle: dict, settings: dict, latex: LatexChecker | None = None) -> list[str]:
    per_band = settings.get("diagnostic_questions_per_band", 2)
    prereq_count = settings.get("prerequisite_question_count", 5)
    problems: list[str] = []
    questions = bundle["diagnostic"]

    expected = per_band * len(BANDS)
    if len(questions) != expected:
        problems.append(f"The diagnostic must have exactly {expected} questions ({per_band} per band); it has "
                        f"{len(questions)}.")  # fmt: skip
    bands = Counter(q["band"] for q in questions)
    for band in BANDS:
        if bands.get(band, 0) != per_band:
            problems.append(f'Band "{band}" must have exactly {per_band} questions; it has {bands.get(band, 0)}.')
    if dupes := _duplicates(q["id"] for q in questions):
        problems.append(f"Question ids must be unique (repeated: {', '.join(dupes)}).")
    if dupes := _duplicates(norm(q["concept"]) for q in questions):
        problems.append(f"Each question must probe a different concept (repeated: {', '.join(dupes)}).")

    for q in questions:
        problems += _options_problems(f"Question {q['id']}", q["options"])
    # Independence: no question may give away another's answer.
    for q in questions:
        answer = norm(q["options"][q["correct_index"]])
        if len(answer) < 6 or answer.replace(" ", "").isdigit():
            continue  # short answers ("3", "O(n)") appear in text by coincidence
        for other in questions:
            if other is not q and answer in norm(other["question"]):
                problems.append(f"Question {other['id']} reveals the answer to {q['id']} (\"{answer}\"); "
                                "questions must be independent.")  # fmt: skip

    prerequisites = bundle["prerequisites"]
    prereq_questions = bundle["prerequisite_questions"]
    if len(prerequisites) != prereq_count:
        problems.append(f"There must be exactly {prereq_count} prerequisites; there are {len(prerequisites)}.")
    if len(prereq_questions) != len(prerequisites):
        problems.append("There must be exactly one prerequisite question per prerequisite.")
    names = [norm(p["name"]) for p in prerequisites]
    if dupes := _duplicates(names):
        problems.append(f"Prerequisites must be different (repeated: {', '.join(dupes)}).")
    mapped = Counter(norm(q["prerequisite"]) for q in prereq_questions)
    for q in prereq_questions:
        if norm(q["prerequisite"]) not in names:
            problems.append(f'Prerequisite question {q["id"]} refers to "{q["prerequisite"]}", which is not one of '
                            "the prerequisites; use the exact name.")  # fmt: skip
        problems += _options_problems(f"Prerequisite question {q['id']}", q["options"])
    for name, prerequisite in zip(names, prerequisites, strict=False):
        if mapped.get(name, 0) != 1:
            problems.append(f'Prerequisite "{prerequisite["name"]}" needs exactly one question.')
    if dupes := _duplicates([q["id"] for q in questions] + [q["id"] for q in prereq_questions]):
        problems.append(f"Ids must be unique across both quizzes (repeated: {', '.join(dupes)}).")

    texts = [q["question"] for q in questions + prereq_questions]
    texts += [o for q in questions + prereq_questions for o in q["options"]]
    problems += _latex(latex, [m for t in texts for m in math_in(t)])
    return problems


def assessment_guard(assessment: dict, prerequisites_to_cover: list[dict]) -> dict:
    """The LLM may explain the gaps but may not change which prerequisites are covered."""
    return {**assessment, "prerequisites_to_cover": [p["name"] for p in prerequisites_to_cover]}


# --- Mastery path ----------------------------------------------------------------------------------------------


def _mentions(text: str, concept: str) -> bool:
    words = [w for w in norm(concept).split() if len(w) > 3] or norm(concept).split()
    haystack = norm(text)
    return sum(w in haystack for w in words) >= max(1, len(words) // 2)


def validate_test_questions(questions: list[dict], label: str = "Question") -> list[str]:
    problems = []
    if dupes := _duplicates(q["id"] for q in questions):
        problems.append(f"Question ids must be unique (repeated: {', '.join(dupes)}).")
    if dupes := _duplicates(norm(q["question"]) for q in questions):
        problems.append(f"Questions must not repeat ({len(dupes)} repeated).")
    for q in questions:
        if q["type"] == "mcq":
            problems += _options_problems(f"{label} {q['id']}", q["options"])
        if q["type"] == "code" and (q.get("language") or "").lower() == "python" and q.get("reference_solution"):
            problems += _python_problems(f"{label} {q['id']} reference solution", q["reference_solution"])
    return problems


def validate_study_material(kind: str, content: dict, concepts: list[str], latex: LatexChecker | None = None):
    problems: list[str] = []
    texts: list[str] = []
    if kind == "cheat_sheet":
        items = [item for section in content["sections"] for item in section["items"]]
        if len(content["sections"]) < 2:
            problems.append("Use at least 2 sections.")
        if len(items) < 6:
            problems.append(f"A cheat sheet needs at least 6 items; it has {len(items)}.")
        if len(items) > 40:
            problems.append("Too long for a cheat sheet: keep it to at most 40 items.")
        for item in items:
            if item["kind"] == "formula" and not item["formula"]:
                problems.append(f'"{item["label"]}" is a formula item but has no formula.')
            texts += [item["content"], item["when_to_use"]]
        expressions = [item["formula"] for item in items] + [v["symbol"] for i in items for v in i["variables"]]
        problems += _latex(latex, expressions + [m for t in texts for m in math_in(t)])
        texts += [item["label"] for item in items]
    elif kind == "revision_sheet":
        subtopics = content["subtopics"]
        if len(subtopics) < 4:
            problems.append(f"Cover every subtopic: at least 4 are needed; there are {len(subtopics)}.")
        for sub in subtopics:
            if len(sub["summary"]) < 150:
                problems.append(f'Subtopic "{sub["title"]}" needs a fuller summary (at least a paragraph).')
            if len(sub["key_points"]) < 3:
                problems.append(f'Subtopic "{sub["title"]}" needs at least 3 key points.')
            texts += [sub["title"], sub["summary"], *sub["key_points"], *sub["common_mistakes"]]
            texts += [part for ex in sub["worked_examples"] for part in (ex["problem"], ex["solution"])]
        problems += _latex(latex, [m for t in texts for m in math_in(t)])
    elif kind == "practice_sheet":
        questions = content["questions"]
        if not 15 <= len(questions) <= 25:
            problems.append(f"A practice sheet has 15-25 questions; it has {len(questions)}.")
        order = [DIFFICULTIES.index(q["difficulty"]) for q in questions]
        if order != sorted(order):
            problems.append("Order the questions from easy to hard.")
        if len({q["type"] for q in questions}) < 3:
            problems.append("Mix at least 3 question types.")
        problems += validate_test_questions(questions)
        texts = [q["question"] for q in questions] + [q["concept"] for q in questions]
        problems += _latex(latex, [m for q in questions for m in math_in(q["question"])])
    else:
        problems.append(f"Unknown study material kind {kind!r}.")

    missing = [c for c in concepts if not any(_mentions(t, c) for t in texts)]
    if missing and len(missing) > len(concepts) // 3:
        problems.append("Cover the topic's key concepts; these are missing: " + "; ".join(missing))
    return problems


# --- Stage B ---------------------------------------------------------------------------------------------------


def validate_plan(plan: dict, settings: dict, prerequisites_to_cover: list[dict]) -> list[str]:
    problems: list[str] = []
    keys = [page["key"] for page in plan["pages"]]
    if sorted(keys) != sorted(PAGE_KEYS):
        problems.append(f"Plan exactly three pages with keys {', '.join(PAGE_KEYS)} (got {', '.join(keys)}).")
    concepts = [norm(item["concept"]) for page in plan["pages"] for item in page["outline"]]
    if dupes := _duplicates(concepts):
        problems.append("Each concept belongs to one page only; repeated across pages: " + ", ".join(dupes))
    for page in plan["pages"]:
        if not 2 <= len(page["outline"]) <= 8:
            problems.append(f'Page "{page["key"]}" needs 2-8 outline parts; it has {len(page["outline"])}.')
    intro = next((p for p in plan["pages"] if p["key"] == "introduction"), None)
    covered = {norm(name) for name in (intro or {}).get("covers_prerequisites", [])}
    for prerequisite in prerequisites_to_cover:
        if norm(prerequisite["name"]) not in covered:
            problems.append(f'The introduction must cover the prerequisite "{prerequisite["name"]}" (list it in '
                            "covers_prerequisites and teach it in the outline).")  # fmt: skip

    spec = plan["final_test"]
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


def _python_problems(label: str, code: str) -> list[str]:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return [f"{label} is not valid Python: {exc.msg} (line {exc.lineno})."]
    return []


def validate_page(page: dict, plan_page: dict, latex: LatexChecker | None = None) -> list[str]:
    problems: list[str] = []
    sections = page["sections"]
    if page["key"] != plan_page["key"]:
        problems.append(f'This page must have key "{plan_page["key"]}".')
    if not 2 <= len(sections) <= 8:
        problems.append(f"Write 2-8 sections; there are {len(sections)}.")
    if dupes := _duplicates(s["id"] for s in sections):
        problems.append(f"Section ids must be unique (repeated: {', '.join(dupes)}).")
    if dupes := _duplicates(norm(s["heading"]) for s in sections):
        problems.append(f"Section headings must be unique (repeated: {', '.join(dupes)}).")
    for section in sections:
        if len(section["body"]) < 200:
            problems.append(f'Section "{section["heading"]}" is too thin: explain it in at least a paragraph.')
    text = " ".join(s["heading"] + " " + s["body"] for s in sections)
    missing = [item["concept"] for item in plan_page["outline"] if not _mentions(text, item["concept"])]
    if missing:
        problems.append("Teach every concept in the plan's outline; missing: " + "; ".join(missing))

    expressions = []
    for section in sections:
        expressions += math_in(section["body"]) + [f["latex"] for f in section["formulas"]]
        expressions += [m for ex in section["worked_examples"] for part in ex.values() for m in math_in(part)]
        for snippet in section["code_snippets"]:
            if snippet["language"].lower() in ("python", "py"):
                problems += _python_problems(f'The code in "{section["heading"]}"', snippet["code"])
    problems += _latex(latex, expressions)
    return problems


def validate_final_test(test: dict, spec: dict, latex: LatexChecker | None = None) -> list[str]:
    questions = test["questions"]
    problems = []
    if len(questions) != spec["question_count"]:
        problems.append(f"Write exactly {spec['question_count']} questions; there are {len(questions)}.")
    types = Counter(q["type"] for q in questions)
    for kind in QUESTION_TYPES:
        if types.get(kind, 0) != spec["type_mix"].get(kind, 0):
            problems.append(f"Write exactly {spec['type_mix'].get(kind, 0)} {kind} questions; there are "
                            f"{types.get(kind, 0)}.")  # fmt: skip
    levels = Counter(q["difficulty"] for q in questions)
    for level in DIFFICULTIES:
        if levels.get(level, 0) != spec["difficulty_mix"].get(level, 0):
            problems.append(f"Write exactly {spec['difficulty_mix'].get(level, 0)} {level} questions; there are "
                            f"{levels.get(level, 0)}.")  # fmt: skip
    problems += validate_test_questions(questions)
    problems += _latex(latex, [m for q in questions for m in math_in(q["question"])])
    return problems


def validate_interactive_plan(plan: dict, pages: dict, settings: dict) -> list[str]:
    problems: list[str] = []
    specs = plan["specs"]
    max_per_page = settings.get("max_interactives_per_page", 3)
    if dupes := _duplicates(s["id"] for s in specs):
        problems.append(f"Interactive ids must be unique (repeated: {', '.join(dupes)}).")
    for spec in specs:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,40}", spec["id"]):
            problems.append(f'Interactive id "{spec["id"]}" must be letters, digits and underscores.')
        page = pages.get(spec["page"])
        if page and spec["anchor_section"] not in {s["id"] for s in page["sections"]}:
            problems.append(f'Interactive "{spec["id"]}" anchors to section "{spec["anchor_section"]}", which '
                            f'doesn\'t exist on the {spec["page"]} page.')  # fmt: skip
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
